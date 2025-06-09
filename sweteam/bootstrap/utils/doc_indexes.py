"""
Issue management system, where issues are stored and indexed for querying
Issue are created, updated and can be listed, and read. 
The issues are saved as json files in a recursive directory structure where 
the directory names represents the hierarchy of the issues (and sub-issues).

The issues are indexed using the llama_index library, which provides a vector store
index for querying the issues. The index is created from the documents in the issue directory.

"""
from .redis_pool import RedisConnectionPool
from .file_utils import dir_contains
from .decorators import timed_async_execution, timed_execution
from .log import get_logger, get_default_logger
from ..config import config
from redis.asyncio import Redis as AsyncRedis, ConnectionPool as AsyncConnectionPool
from abc import ABC, abstractmethod
from typing import cast

from llama_index.core.indices.base import BaseIndex
import nest_asyncio

import os
import json
import hashlib
from llama_index.core import (VectorStoreIndex, load_index_from_storage,
                              RAKEKeywordTableIndex, SummaryIndex,
                              SimpleDirectoryReader, StorageContext, Settings, Document)
from llama_index.core.schema import BaseNode
from llama_index.core.node_parser import SentenceSplitter, JSONNodeParser
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES

from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.storage.docstore.redis.base import RedisKVStore
from llama_index.vector_stores.redis import RedisVectorStore
from llama_index.storage.index_store.redis import RedisIndexStore
from llama_index.storage.docstore.redis import RedisDocumentStore


from redisvl.schema import IndexSchema
nest_asyncio.apply()


# bge-m3 embedding model uses 1024 dimmesions
embedding_dim = 1024
ollama_embedding = OllamaEmbedding(
    model_name=config.OLLAMA_EMBEDDING_MODEL,
    base_url=config.OLLAMA_URL,
    ollama_additional_kwargs={"mirostat": 0},
)

Settings.embed_model = ollama_embedding

Settings.llm = Ollama(model=config.OLLAMA_DEFAULT_BASE_MODEL,
                      base_url=config.OLLAMA_URL,
                      request_timeout=360.0)


class Source(ABC):
    """This is the base class used to get documents and metadata from various sources.
    The Issue Manger indexes issue tickets, by retrieving the issue tickets from the source
    For the IssueManager to be able to udnerstand the contents of the issues from different sources, 
    Each source needs a wrapper derived from this class - read the raw source data and convert them to
    a standard format that IssueManager can index.
    """
    @abstractmethod
    async def get_all_documents(self) -> list[Document]:
        """Returns all the documents as whole as a list
        The IssueManager will need the source document (i.e. each ticket) to be a Document object
        which is defined by llama-index, methods like SimpleDirectoryReader().load_data() will 
        return a list[Document]
        Args:
            None
        Returns:
            list[Document]
        """
        pass

    @abstractmethod
    async def get_all_metadata(self) -> dict:
        """Returns all the metadata of each document (i.e. an issue, or a file) should
        be sufficient to identify if the document has changed without having to go 
        through the full cycle of retrieving the full document from the source.
        This is used to provide a document list, and/or compare if a document needs to be refreshed
        Args:
            None
        Returns:
            dict: keys are the ids of the document, value are the namespace specific metadata key:value pairs
        """
        pass

    @abstractmethod
    async def get_documents(self, doc_id_list: list[str]) -> list[Document]:
        """Retrieve a group of documents by their ids. Should be a subset of what get_all_documents return
        which means the metadata should be provided consistently as the get_all_documents()
        Args:
            doc_id_list: a list of strings that specifies the documents to retrieve
        Returns:
            list[Document]
        """
        pass


class Files(Source):
    """Interface class to abstract files to documents conversion
    it uses SimpleDirectoryReader() to read all documents preserving their full_path
    """

    def __init__(self, path_: str, namespace: str = ""):
        self.logger = get_default_logger(self.__class__.__name__)
        self.namespace = namespace or config.PROJECT_NAME
        self.path = os.path.abspath(path_) + "/"
        if not os.path.exists(self.path):
            self.logger.info("Issue directory does not exist, creating it...")
            os.makedirs(self.path, exist_ok=True)

    async def get_file_hash(self, file_path: str, algorithm: str = 'sha256', buffer_size: int = 65536) -> str:
        """Calculate the hash of a file efficiently using buffered reading."""
        hash_func = hashlib.new(algorithm)

        with open(file_path, 'rb') as f:
            while True:
                data = f.read(buffer_size)
                if not data:
                    break
                hash_func.update(data)

        return hash_func.hexdigest()

    async def get_all_documents(self) -> list[Document]:
        """Return list of llama-index Document objects with special meta data"""
        documents = []
        if os.path.exists(self.path) and dir_contains(self.path, recursive=True):
            self.logger.info("Issue directory <%s> found, using it...", self.path)
            reader = SimpleDirectoryReader(self.path, recursive=True)
            documents = reader.load_data()
            for document in documents:
                if hasattr(document, "metadata"):
                    file_path = document.metadata["file_path"]
                    metadata = {
                        "id": file_path.removeprefix(self.path),
                        "size": document.metadata["file_size"]}
                    await self.get_metadata(os.stat(file_path), metadata)
                    for k, v in metadata.items():
                        document.metadata[f"{self.namespace}{k}"] = v
                else:
                    self.logger.warning("Document %s does not have metadata, this is strange!", document)

        return documents

    async def get_documents(self, doc_id_list: list) -> list[Document]:
        """Retrieve standard file system level info as file metadata"""
        documents = []
        doc_path_list = [os.path.join(self.path, id) for id in doc_id_list]
        if any([os.path.exists(f) for f in doc_path_list]):
            documents = await SimpleDirectoryReader(input_files=doc_path_list).aload_data()
            for document in documents:
                if hasattr(document, "metadata"):
                    file_path = document.metadata["file_path"]
                    metadata = {
                        "id": file_path.removeprefix(self.path),
                        "size": document.metadata["file_size"]}
                    await self.get_metadata(os.stat(file_path), metadata)
                    try:
                        file_content = json.loads(document.text)
                    except Exception as e:
                        self.logger.warning("File %s content is not valid json", file_path)
                        file_content = {}

                    metadata["title"] = file_content.get("title") or file_content.get("Summary")
                    for k, v in metadata.items():
                        document.metadata[f"{self.namespace}{k}"] = v
                else:
                    self.logger.warning("Document %s does not have metadata, this is strange!", document)

        return documents

    async def get_metadata(self, os_stat, metadata: dict = {}) -> dict:
        """Return metadata that are compatible with {doc_id: {doc_size:int, updated_at:datetime}}"""
        metadata.setdefault(f"{self.namespace}size", os_stat.st_size)
        metadata.setdefault(f"{self.namespace}created_at", os_stat.st_ctime)
        metadata.setdefault(f"{self.namespace}updated_at", os_stat.st_mtime)

        return metadata

    async def get_all_metadata(self) -> dict:
        """Return metadata that are compatible with {doc_id: {doc_size:int, updated_at:datetime}}"""
        file_metadata = {}

        async def scan_dir_populate_metadata(dir_path):
            nonlocal file_metadata
            for entry in os.scandir(dir_path):
                if entry.is_file():  # Check if it's a file
                    file_path = os.path.abspath(entry.path)
                    _doc_id = file_path.removeprefix(dir_path)
                    metadata = {f"{self.namespace}id": _doc_id}
                    await self.get_metadata(os.stat(file_path), metadata)
                    file_metadata[_doc_id] = metadata
                elif entry.is_dir():  # Recurse into subdirectories
                    await scan_dir_populate_metadata(entry.path)

        await scan_dir_populate_metadata(self.path)
        return file_metadata


class IndexStore():
    """Using docstore, vector_store and index_store to facilitate queries contents of documents
    This implementation uses Redis for all three stores. Once documents are read and loaded, 
    will create 3 indexes: SummaryIndex, KeywordTableIndex and VectorIndex. 
    Then create a fusion query engine to enable query using all 3 indexes. 
    """

    def __init__(self, source: Source, index_schema: dict | None = None,
                 redis_connection_pool: RedisConnectionPool | None = None,
                 namespace: str = "", reset: bool = False) -> None:
        self.logger = get_default_logger(self.__class__.__name__)
        self.namespace = namespace or config.PROJECT_NAME
        self.index_schema = cast(IndexSchema, index_schema)
        if (not hasattr(self, "name")):
            self.name = {self.__class__.__name__}

        self.source = source
        self.indexes: dict[str, (SummaryIndex | RAKEKeywordTableIndex | VectorStoreIndex | BaseIndex)] = {}
        self.reset = reset

        # Create Redis clients
        self.logger.debug("creating Redis clients... %s:%s", config.REDIS_HOST, config.REDIS_PORT)
        self.redis_pool = redis_connection_pool or RedisConnectionPool()
        self.redis_client = self.redis_pool.get_client(host=config.REDIS_HOST,
                                                       port=config.REDIS_PORT,
                                                       password=config.REDIS_PASSWORD,
                                                       username=config.REDIS_USERNAME,
                                                       db=0)
        self.async_redis_client = self.redis_pool.get_async_client(host=config.REDIS_HOST,
                                                                   port=config.REDIS_PORT,
                                                                   password=config.REDIS_PASSWORD,
                                                                   username=config.REDIS_USERNAME,
                                                                   db=0)
        #  create RedisKVStore to be used by indexes
        self.redis_kvstore = RedisKVStore(redis_client=self.redis_client,
                                          async_redis_client=self.async_redis_client)
        self.redis_client.publish(f"{self.namespace}{self.name}/status_channel",
                                  '{"status": "initializing", "message": "Refreshing Issues..."}')

    async def initialize(self) -> None:
        """Initialize the IndexStore asynchronously"""

        self.logger.debug("Redis clients created: %s", await self.async_redis_client.ping())

        try:
            # try to reconnect to storage_context and retrieve vectorindex/summary&keyword index/docs
            index_list = await self.async_redis_client.execute_command("FT._LIST")
            if index_list is None or f"{self.namespace}vector".encode('utf-8') not in index_list:
                raise IndexError("Vector Index not found in Redis")

            redis_keys = await self.async_redis_client.execute_command("keys", f"{self.namespace}*")
            for store_type in ["doc", "index"]:
                if redis_keys is None or f"{self.namespace}/{store_type}".encode('utf-8') not in redis_keys:
                    raise IndexError(f"{store_type} store is not found in Redis")

            # if all 3 stores are found to be in Redis already:
            self.storage_context = await self.connect_to_redis_stores()

            self.indexes["vector_index"] = VectorStoreIndex.from_vector_store(
                vector_store=self.storage_context.vector_store
            )
            self.indexes["summary_index"] = cast(SummaryIndex, load_index_from_storage(
                self.storage_context, index_id=f"{self.name}_summary"
            ))
            self.indexes["keyword_index"] = cast(RAKEKeywordTableIndex, load_index_from_storage(
                self.storage_context, index_id=f"{self.name}_keyword"
            ))

            # Create retrievers from each index
            summary_retriever = self.indexes["summary_index"].as_retriever()
            vector_retriever = self.indexes["vector_index"].as_retriever()
            keyword_retriever = self.indexes["keyword_index"].as_retriever()

            # Combine retrievers using fusion
            fusion_retriever = QueryFusionRetriever(
                retrievers=[summary_retriever, vector_retriever, keyword_retriever],
                similarity_top_k=3,
                num_queries=1,
                mode=FUSION_MODES.SIMPLE
            )

            # Create a query engine from the fusion retriever
            self.query_engine = RetrieverQueryEngine.from_args(
                retriever=fusion_retriever
            )

        except Exception as e:
            # if storage_context can't be loaded from storage, call create_index() to build it.
            self.query_engine = await self.create_index(force=(self.reset is True))

        self.logger.debug(f"initialized Issue Index Vector Store...")

        await self.load_documents(await self.source.get_all_documents(), force=self.reset)
        self.redis_client.publish(f"{self.namespace}{self.name}/status_channel",
                                  '{"status": "ready", "message": "Issues refreshed."}')

        self.logger.debug("Loaded / refreshed documents for all indexes")

    def docs_to_nodes(self, documents) -> list[Document | BaseNode]:
        """Convert documents to nodes."""
        nodes = []
        try:
            nodes = JSONNodeParser().get_nodes_from_documents(documents)
            self.logger.debug("Parsed %s document as %s nodes.", len(documents), len(nodes))
        except Exception as e:
            self.logger.warning("could not load all files as json, parsing individually...")
            for document in documents:
                try:
                    json.JSONDecoder().decode(document)
                    nodes_ = JSONNodeParser().get_nodes_from_documents(document)
                    self.logger.debug("document parsed as %s JSON nodes", len(nodes_))
                    nodes.extend(nodes_)
                except Exception:
                    nodes_ = SentenceSplitter().get_nodes_from_documents(documents)
                    self.logger.debug("document parsed as %s plain text nodes", len(nodes_))
                    nodes.extend(nodes_)
        return nodes

    async def connect_to_redis_stores(self) -> StorageContext:
        """Connect to Redis stores and return storage context."""
        # VectorStore does not support using redis_kvstore to provide both sync and async clients
        vector_store = RedisVectorStore(
            redis_client=self.redis_client,
            overwrite=False,
            schema=self.index_schema
        )

        # self.redis_kvstore is configured with both sync and async clients
        index_store = RedisIndexStore(redis_kvstore=self.redis_kvstore,
                                      namespace=f"{self.namespace}"
                                      )

        doc_store = RedisDocumentStore(redis_kvstore=self.redis_kvstore,
                                       namespace=f"{self.namespace}"
                                       )

        return StorageContext.from_defaults(
            docstore=doc_store,
            vector_store=vector_store,
            index_store=index_store
        )

    async def create_index(self, force: bool = False):
        """Create or recreate the indexes."""
        if force:
            self.logger.info("force=%s specified, flushing all in Redis", force)
            await self.async_redis_client.execute_command("flushall")

        index_list = await self.async_redis_client.execute_command("FT._LIST")
        self.logger.debug("Existing indexes: %s", index_list)

        if index_list and f"{self.namespace}vector".encode('utf-8') in index_list:
            self.logger.info("Index %svector already exists, checking compatibility...", self.namespace)
            info = await self.async_redis_client.execute_command("FT.INFO", f"{self.namespace}vector")
            if info:
                info_dict = {info[i]: info[i + 1] for i in range(0, len(info), 2)}
                stored_attributes = info_dict.get(b"attributes", [])
                list_of_dict_attributes = [{attr[i]: attr[i + 1] for i in range(0, len(attr), 2)}
                                           for attr in stored_attributes]
                stored_fields_set = {(attr.get(b"identifier") or attr.get(b"type") or b"").decode().lower()
                                     for attr in list_of_dict_attributes}
                if hasattr(self.index_schema, "to_dict"):
                    defined_schema = self.index_schema.to_dict()
                    defined_fields = defined_schema.get("fields", [])
                    defined_fields_set = {(field.get("name"), field.get("type")) for field in defined_fields.values()}
                else:
                    defined_schema = self.index_schema
                    defined_fields = defined_schema.fields
                    defined_fields_set = {(field.name, field.type) for field in defined_fields.values()}
                if stored_fields_set == defined_fields_set:
                    self.logger.info("Index %s.vector is compatible with defined schema", self.name)
                else:
                    self.logger.warning(
                        "data in the index is imcompatible with defined schema: index_store=%s, instead of %s", stored_fields_set, defined_fields_set)
                    await self.async_redis_client.execute_command("FT.DROPINDEX", f"{self.namespace}vector")
                    index_list = await self.async_redis_client.execute_command("FT._LIST")
                    self.logger.info("Index %svector dropped. Remaining indexes are:%s", self.namespace, index_list)

        self.storage_context = await self.connect_to_redis_stores()

        vector_index = VectorStoreIndex.from_vector_store(
            vector_store=self.storage_context.vector_store
        )

        self.indexes["vector_index"] = vector_index
        all_nodes = []

        try:
            summary_index = load_index_from_storage(
                storage_context=self.storage_context,
                index_id=f"{self.name}_summary"
            )
        except Exception as e:
            self.logger.warning(
                "Unable to load and refresh summaryindex from storage, will re-create. Error detail: %s ", e)
            summary_index = SummaryIndex(
                nodes=all_nodes,
                storage_context=self.storage_context, use_async=True
            )
            summary_index.set_index_id(f"{self.name}_summary")
        self.indexes["summary_index"] = summary_index

        try:
            keyword_index = load_index_from_storage(
                storage_context=self.storage_context,
                index_id=f"{self.name}_keyword"
            )
        except Exception as e:
            self.logger.warning(
                "Unable to load and refresh keywordindex from storage, will re-create. Error detail: %s", e)
            keyword_index = RAKEKeywordTableIndex(
                nodes=all_nodes,
                storage_context=self.storage_context
            )
            keyword_index.set_index_id(f"{self.name}_keyword")
        self.indexes["keyword_index"] = keyword_index

        # Create retrievers from each index
        summary_retriever = summary_index.as_retriever()
        vector_retriever = vector_index.as_retriever()
        keyword_retriever = keyword_index.as_retriever()

        # Combine retrievers using fusion
        fusion_retriever = QueryFusionRetriever(
            retrievers=[summary_retriever, vector_retriever, keyword_retriever],
            similarity_top_k=5,
            num_queries=1,
            mode=FUSION_MODES.SIMPLE
        )

        # Create a query engine from the fusion retriever
        fusion_query_engine = RetrieverQueryEngine.from_args(
            retriever=fusion_retriever
        )

        return fusion_query_engine

    async def delete_docs(self, doc_id_set: set = set()):
        deleting_list_key = f'{self.namespace}{self.name}_deleting_docs'

        unfinished_deletes_b = await self.async_redis_client.get(deleting_list_key)
        unfinished_deletes = json.loads(unfinished_deletes_b) if unfinished_deletes_b else []

        docs_to_remove = list(doc_id_set.union(unfinished_deletes))

        self.redis_client.set(deleting_list_key, json.dumps(docs_to_remove))
        for index_name, index in self.indexes.items():
            docs_removed = 0
            nodes_removed = 0
            need_to_remove_nodes_docs = []
            # Try gracefully delete using index, in exception, fallback to per node removal
            for doc_id in docs_to_remove:
                try:
                    if hasattr(index, 'adelete_ref_doc'):
                        await index.adelete_ref_doc(ref_doc_id=doc_id) # type: ignore
                        docs_removed += 1
                    elif hasattr(index, 'adelete'):
                        await index.adelete(doc_id=doc_id) # type: ignore
                        docs_removed += 1
                    else:
                        index.delete_ref_doc(ref_doc_id=doc_id)
                        docs_removed += 1
                except Exception as e:
                    self.logger.warning(
                        "Deleting doc %s failed with %s, trying to use it as Source Doc ID...", doc_id, e)
                    for doc_id_mapped in [dk for dk, dv in index.docstore.docs.items()
                                          if dv.metadata[f'{self.namespace}id'] == doc_id]:
                        try:
                            index.delete_ref_doc(ref_doc_id=doc_id_mapped)
                            docs_removed += 1
                        except Exception as e:
                            self.logger.warning(
                                "Deleting doc %s as source id also failed with %s, try deleting nodes", doc_id, e)
                            need_to_remove_nodes_docs.append(doc_id)

            doc_nodes_to_remove = []
            index_nodes = (index.index_struct.nodes if hasattr(index.index_struct, 'nodes') # type: ignore
                           else index.index_struct.nodes_dict.keys() if hasattr(index.index_struct, 'nodes_dict') # type: ignore
                           else index.docstore.docs)
            for node_id in index_nodes:
                try:
                    if (index.docstore.get_node(node_id).metadata[f"{self.namespace}id"] in need_to_remove_nodes_docs
                            or index.docstore.get_node(node_id).ref_doc_id in need_to_remove_nodes_docs):
                        doc_nodes_to_remove.append(node_id)
                except Exception as e:
                    self.logger.warning("Node %s does not have metadata, will try to delete it anyway...", node_id)
                    doc_nodes_to_remove.append(node_id)
            try:
                delete_methods = ['adelete_ref_doc', 'adelete_notes', 'adelete']
                for dm in delete_methods:
                    if hasattr(index, dm):
                        func = getattr(index, dm)
                        break
                await timed_async_execution(func, node_ids=doc_nodes_to_remove)
            except Exception as e:
                self.logger.warning("Asyn deleting nodes methods are unavailable, try sync deletion")
                delete_methods = ['delete_ref_doc', 'delete_notes', 'delete']
                for dm in delete_methods:
                    if hasattr(index, dm):
                        func = getattr(index, dm)
                        break
                timed_execution(func, node_ids=doc_nodes_to_remove)

            nodes_removed += len(doc_nodes_to_remove)
            self.logger.debug("Removed %s docs and %s nodes from %s.", docs_removed, nodes_removed, index.index_id)

        # Delete from doc store
        doc_remove_count = 0
        node_remove_count = 0
        need_to_delete_by_nodes = False
        for doc_to_remove in docs_to_remove:
            self.logger.debug("Removing %s from docstore...", doc_to_remove)
            try:
                await self.storage_context.docstore.adelete_ref_doc(ref_doc_id=doc_to_remove)
                doc_remove_count += 1
            except Exception as e:
                self.logger.warning("Removing %s from DocStore run into error, will try to delete nodes "
                                    "with metadata pointing to it...", doc_to_remove, exc_info=e)
                need_to_delete_by_nodes = True

        if need_to_delete_by_nodes:
            for node_id, node in self.storage_context.docstore.docs.items():
                # node_id = node.node_id
                if (hasattr(node, "metadata") and node.metadata.get(f"{self.namespace}id") in docs_to_remove
                        or node.ref_doc_id in docs_to_remove):
                    node_remove_count += 1
                    self.logger.debug("Removing %s belonging to DocId %s...", node_id,
                                      node.metadata.get(f"{self.namespace}id"))
                    await self.storage_context.docstore.adelete_document(doc_id=node_id)

        self.logger.debug("Removed %s document and %s nodes from docstore",
                          doc_remove_count, node_remove_count)
        await self.async_redis_client.set(deleting_list_key, '[]')

    async def load_documents(self, document_list: list[Document] = [], force: bool = False):
        """Load documents into the index stores."""

        async def extract_stored_document_metadata(nodes) -> dict[str, dict]:
            stored_metadata = {}
            for node in nodes:
                if hasattr(node, "metadata") and f"{self.namespace}id" in node.metadata:
                    _doc_id = node.doc_id if hasattr(node, 'doc_id') else node.metadata[f"{self.namespace}id"]
                    node_id = node.node_id if hasattr(node, 'node_id') else _doc_id
                    n_metadata = {}
                    for k, v in node.metadata.items():
                        if k.startswith(f"{self.namespace}"):
                            n_metadata[k] = v
                    stored_metadata[node_id] = n_metadata
            return stored_metadata

        all_nodes = list(self.storage_context.docstore.docs.values())
        self.logger.debug("Found %s nodes in storage", len(all_nodes))
        stored_metadata = await timed_async_execution(extract_stored_document_metadata, all_nodes)
        self.logger.debug("Found %s documents with %s metadata", len(stored_metadata), self.namespace)

        if document_list:
            source_docs_metadata = {d.metadata[f"{self.namespace}id"]: d.metadata
                                    for d in document_list if hasattr(d, "metadata")}
        else:
            source_docs_metadata = await self.source.get_all_metadata()

        docs_to_remove = set()
        docs_to_add = set()
        for _doc_id, metadata in source_docs_metadata.items():
            if force:
                self.logger.debug("force=True specified, adding File %s ...", _doc_id)
                docs_to_add.add(_doc_id)
            elif ((matching_docs_metadata := [v for k, v in stored_metadata.items()
                                              if v[f"{self.namespace}id"] == _doc_id]) == []):
                self.logger.debug("Source doc %s was not found in the docstore, will be added...", _doc_id)
                docs_to_add.add(_doc_id)
            elif metadata not in matching_docs_metadata:
                self.logger.debug("Source doc %s metadata do not match docstore, will be replaced... "
                                  "Source metadata: %s; Stored metadata list: %s", _doc_id, metadata, matching_docs_metadata)
                docs_to_remove.add(_doc_id)
                docs_to_add.add(_doc_id)
            else:
                self.logger.debug("Source doc %s was not changed compare to docstore, skipping", _doc_id)

        for stored__doc_id, metadata in [(v[f"{self.namespace}id"], v) for k, v in stored_metadata.items()]:
            if force:
                self.logger.debug("force=True specified, removing File %s ...", stored__doc_id)
                docs_to_remove.add(stored__doc_id)
            elif stored__doc_id not in source_docs_metadata:
                self.logger.debug("%s not found in source, removing ...", stored__doc_id)
                docs_to_remove.add(stored__doc_id)

        # Delete from indexes
        await timed_async_execution(self.delete_docs, docs_to_remove)

        # Remove from cache
        cache_remove_count = 0
        redis_json_prefix = self.namespace + "RJ:"
        for dtr in docs_to_remove:
            rc = await self.async_redis_client.execute_command("DEL", redis_json_prefix + dtr)
            self.logger.debug("%s cached document matching %s were removed...", rc, dtr)
            cache_remove_count += rc
        self.logger.debug("Removed %s documents from cache", cache_remove_count)

        # Add new documents
        new_documents = []
        if docs_to_add:
            if document_list:
                new_documents = [d for d in document_list if d.metadata[f"{self.source.namespace}id"] in docs_to_add]
            else:
                new_documents = await self.source.get_documents(doc_id_list=docs_to_add)

            self.logger.debug("Determined %s new/modified documents to load", len(docs_to_add))

        # Cache the original documents
        try:
            redis_json_prefix = self.namespace + "RJ:"
            for new_doc in new_documents:
                orig_doc = dict(new_doc.text_resource or new_doc.text)
                orig_doc["metadata"] = new_doc.metadata
                orig_doc_id = redis_json_prefix + new_doc.metadata[f"{self.namespace}id"]
                await self.async_redis_client.execute_command(
                    "JSON.SET",
                    orig_doc_id,
                    ".",
                    json.dumps(orig_doc)
                )
        except Exception as e:
            self.logger.warning("Unable to process orig doc as JSON, will skip caching in Redis...", exc_info=e)

        # Insert new documents to indexes
        new_nodes = timed_execution(self.docs_to_nodes, new_documents)
        await timed_async_execution(self.indexes["vector_index"]._async_add_nodes_to_index, index_struct=self.indexes["vector_index"].index_struct, nodes=new_nodes)
        timed_execution(self.indexes["summary_index"].insert_nodes, new_nodes)
        await timed_async_execution(self.indexes["keyword_index"]._async_add_nodes_to_index, index_struct=self.indexes["keyword_index"].index_struct, nodes=new_nodes)

    async def get_cached_doc_metadata(self) -> dict:
        """Retrieve cached document metadata from Redis."""
        redis_json_prefix = self.namespace + "RJ:"
        metadata = {}
        try:
            if self.async_redis_client:
                redisjson_keys = await self.async_redis_client.execute_command("KEYS", f"{redis_json_prefix}*")
            else:
                redisjson_keys = self.redis_client.execute_command("KEYS", f"{redis_json_prefix}*")
            for k in redisjson_keys:
                if self.async_redis_client:
                    b_value = await self.async_redis_client.execute_command("JSON.GET", k)
                else:
                    b_value = self.redis_client.execute_command("JSON.GET", k)
                cached_doc = json.loads(b_value or {})
                if isinstance(k, bytes):
                    k = k.decode('utf-8')
                metadata[k] = cached_doc["metadata"]
        except Exception as e:
            self.logger.warning("Error retrieving cached doc metadata", exc_info=e)
        return metadata

    async def get_cached_documents(self, doc_id_list: list = []) -> list[dict]:
        """Get cached documents from Redis."""
        redis_json_prefix = self.namespace + "RJ:"
        docs = []
        for doc_id in doc_id_list:
            if self.async_redis_client:
                b_doc = await self.async_redis_client.execute_command("JSON.GET", redis_json_prefix + doc_id, ".")
            else:
                b_doc = self.redis_client.execute_command("JSON.GET", redis_json_prefix + doc_id, ".")
            if b_doc:
                docs.append(json.loads(b_doc))
        return docs

    async def query(self, question: str):
        """Query the index about the content indexed"""
        response = await self.query_engine.aquery(question)
        self.logger.debug("answered query '%s' with '%s'", question, response)
        return response.response

    async def refresh(self):
        """Refresh the index with latest documents"""
        await self.load_documents(force=True)
        return "Index refreshed"

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if getattr(self, 'async_redis_client', None):
                await self.async_redis_client.close()
            if getattr(self, 'redis_client', None):
                self.redis_client.close()
            if getattr(self, 'redis_connection_pool', None):
                self.redis_connection_pool.disconnect()
            if getattr(self, 'async_redis_connection_pool', None):
                await self.async_redis_connection_pool.disconnect()
        except Exception as e:
            self.logger.warning("Error closing Redis connections: %s", e)
