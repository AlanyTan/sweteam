from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from redis import Redis
import uvicorn
import sys
import os
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import nest_asyncio  # Add this import

# Apply nest_asyncio right after imports
nest_asyncio.apply()
import asyncio
from sse_starlette.sse import EventSourceResponse

from .utils import timed_async_execution
from .utils.log import get_default_logger
from .utils.issue_management import IssueManager
from .utils.redis_pool import RedisConnectionPool
from .config import config


class ChatMessage(BaseModel):
    message: str
    issue_id: str


class UserInput(BaseModel):
    input_text: str


class IssueManagementApp:
    def __init__(self, redis_pool: Optional[RedisConnectionPool] = None):
        self.logger = get_default_logger(self.__class__.__name__)
        self.redis_pool = redis_pool or RedisConnectionPool()
        self.app = FastAPI()
        self._setup_routes()
        self._setup_static_files()
        self._setup_templates()
        self.issue_manager = None
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
        # Add startup and shutdown events
        self.app.add_event_handler("startup", self.startup_event)
        self.app.add_event_handler("shutdown", self.shutdown_event)

        self.initialization_task: Optional[asyncio.Task] = None
        self.initialized = asyncio.Event()

    def __enter__(self):
        # Setup logic for the context manager
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        # Cleanup logic for the context manager
        pass

    def _setup_static_files(self):
        """Set up static files directory"""
        static_dir_name = "static"
        my_dir = os.path.dirname(__file__)
        static_dir = os.path.join(my_dir, static_dir_name)
        self.logger.debug("Setting up %s directory pointing to %s...", static_dir_name, static_dir)
        self.app.mount("/static", StaticFiles(directory=static_dir), name=static_dir_name)

    def _setup_templates(self):
        """Set up Jinja2 templates"""
        template_dir_name = "templates"
        my_dir = os.path.dirname(__file__)
        template_dir = os.path.join(my_dir, template_dir_name)
        self.logger.debug("Setting up %s directory at %s...", template_dir_name, template_dir)
        self.templates = Jinja2Templates(directory=template_dir)

    async def startup_event(self):
        """Initialize the IssueManager on startup"""
        self.logger.debug("Setting up issue_manager for the FastAPI app...")
        self.issue_manager = IssueManager(redis_connection_pool=self.redis_pool)
        self.initialization_task = asyncio.create_task(self.issue_manager.initialize())
        asyncio.create_task(self.monitor_ready_status())
        self.logger.debug(
            "Finished Setting up issue_manager for the FastAPI app, handling initialization to separate task...")
        return self.issue_manager

    async def shutdown_event(self):
        """Cleanup the IssueManager on shutdown"""
        self.logger.debug("Shutting down FastAPI app, including the issue_manager...")
        if self.initialization_task:
            self.initialization_task.cancel()
            try:
                await self.initialization_task
            except asyncio.CancelledError:
                pass

        if self.issue_manager:
            await self.issue_manager.__aexit__(None, None, None)

    async def monitor_ready_status(self):
        """Subscribe to Redis pub/sub on "status_channel" and set self.initialized when status is 'ready'."""
        if self.async_redis_client:
            pubsub = self.async_redis_client.pubsub()
            await pubsub.subscribe(f"{self.issue_manager.namespace}{self.issue_manager.name}/status_channel")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    try:
                        msg = json.loads(data)
                        if msg.get("status") == "ready":
                            self.logger.debug("Received 'ready' status via async client. Setting initialized event.")
                            self.initialized.set()
                            break
                    except json.JSONDecodeError:
                        if data.strip() == "ready":
                            self.logger.debug(
                                "Received plain 'ready' status via async client. Setting initialized event.")
                            self.initialized.set()
                            break
        else:
            # Fallback to synchronous Redis client
            pubsub = self.redis_client.pubsub()
            pubsub.subscribe(f"{self.issue_manager.namespace}{self.issue_manager.name}/status_channel")
            while True:
                message = pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    try:
                        msg = json.loads(data)
                        if msg.get("status") == "ready":
                            self.logger.debug("Received 'ready' status via sync client. Setting initialized event.")
                            self.initialized.set()
                            break
                    except json.JSONDecodeError:
                        if data.strip() == "ready":
                            self.logger.debug(
                                "Received plain 'ready' status via sync client. Setting initialized event.")
                            self.initialized.set()
                            break
                await asyncio.sleep(0.1)

    def _setup_routes(self):
        """Set up all routes for the application"""
        self.logger.debug("Setting up FastAPI routes...")
        self.app.get("/")(self.get_issue_chat_page)
        self.app.get("/api/issues/{issue_id}")(self.get_issue)
        self.app.post("/api/chat")(self.chat)
        self.app.get("/api/issues")(self.list_issues)
        self.app.get("/api/status")(self.status_endpoint)

    async def status_endpoint(self, request: Request):
        async def event_generator():
            if self.initialized.is_set():
                yield {"event": "message", "data": '{"status": "ready", "message": "Already initialized"}'}
            elif self.async_redis_client is None:
                pubsub = self.redis_client.pubsub()
                pubsub.subscribe(f"{self.issue_manager.namespace}{self.issue_manager.name}/status_channel")
                try:
                    while True:
                        message = pubsub.get_message(timeout=0.1)
                        if message and message["type"] == "message":
                            yield {"event": "message", "data": message["data"].decode()}
                        await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    pubsub.unsubscribe(f"{self.issue_manager.namespace}{self.issue_manager.name}/status_channel")
                    raise
            else:
                pubsub = self.async_redis_client.pubsub()
                await pubsub.subscribe(f"{self.issue_manager.namespace}{self.issue_manager.name}/status_channel")
                try:
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            yield {"event": "message", "data": message["data"].decode()}
                except asyncio.CancelledError:
                    await pubsub.unsubscribe(f"{self.issue_manager.namespace}{self.issue_manager.name}/status_channel")
                    raise

        return EventSourceResponse(event_generator())

    async def get_issue_list(self) -> list:
        """Get list of all issues with basic information"""
        issues = await self.issue_manager.get_cached_doc_metadata() or await self.issue_manager.source.get_all_metadata()
        issues_list = []
        for k, v in issues.items():
            issues_list.append({
                'id': v.get(f"{self.issue_manager.namespace}id", k),
                'title': (v.get('title') or v.get(f'{self.issue_manager.namespace}title'))[:80]
            })
        return issues_list

    async def get_issue_chat_page(self, request: Request) -> HTMLResponse:
        """Serve the issue chat page."""
        issues_list = await self.get_issue_list()
        return self.templates.TemplateResponse(
            "issue_chat.html",
            {"request": request, "issues": issues_list}
        )

    async def get_issue(self, issue_id: str) -> Dict[str, Any]:
        """Get details for a specific issue."""
        try:
            cached_issues = await self.issue_manager.get_cached_documents([issue_id])
            if cached_issues:
                found_issue_raw = cached_issues[0]
                found_issue_metadata = found_issue_raw["metadata"]
            else:
                found_issues = await self.issue_manager.source.get_documents([issue_id])
                found_issue_raw = dict(found_issues[0]) if found_issues else {}
                found_issue_metadata = found_issue_raw["metadata"]

            if "text" in found_issue_raw:
                # if this is direct loaded from file by SimpleDirectoryReader .etc
                found_issue = json.loads(found_issue_raw.get("text"))
            else:
                # if this is created by Document(...)
                found_issue = dict(found_issue_raw.get("text_resource"))

            if found_issue:
                issue = {}
                issue["id"] = issue_id
                issue["title"] = found_issue_metadata.get(f"{self.issue_manager.namespace}title", "no title")
                issue["created"] = found_issue_metadata.get(f"{self.issue_manager.namespace}created_at", "unknown")
                issue["updated"] = found_issue_metadata.get(f"{self.issue_manager.namespace}updated_at", "unknown")
                issue["status"] = found_issue_metadata.get(f"{self.issue_manager.namespace}status", "unknown")

                # Process description
                description = found_issue.get("description") or found_issue.get("text", '{}')
                issue["description"] = self._parse_json_string(description)

                # Process comments
                comments = found_issue.get("comment") or found_issue.get("comments", '{}')
                issue["comments"] = self._parse_json_string(comments)

                # Process changelog
                changelog = found_issue.get("changelog") or found_issue.get("updates", '{}')
                issue["changelog"] = self._parse_json_string(changelog)

                # Process additional attributes
                issue["attributes"] = {}
                for key, value in found_issue.items():
                    if key not in ["description", "comments", "changelog"]:
                        issue["attributes"][key] = value

                return issue
        except Exception as e:
            self.logger.warning("Error retrieving document %s from the source, due to %s", issue_id, e, exc_info=e)
            return {"message": "Issue not found", "error": 404}

    def _parse_json_string(self, data: Any) -> Any:
        """Helper method to parse JSON strings"""
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data
        return data

    async def chat(self, message: ChatMessage) -> Dict[str, str]:
        """Process a chat message and return an AI response."""
        try:
            query = f"Regarding issue {message.issue_id}: {message.message}"

            try:
                response = await timed_async_execution(self.issue_manager.query, query)
                ai_response = str(response.response)
            except Exception as e:
                ai_response = f"I run into error querying issue manager: {e}"

            return {"response": ai_response}

        except Exception as e:
            self.logger.error(f"Error in chat endpoint: {e}")
            return {"response": "I'm sorry, I encountered an error while processing your request."}

    async def list_issues(self) -> list:
        """List all available issues."""
        return await timed_async_execution(self.get_issue_list)

    def run(self):
        """Start the FastAPI application server"""
        self.logger.info("Starting Issue Management Assistant server...")
        print("Access the web interface at http://localhost:8000")
        uvicorn.run(self.app, host="0.0.0.0", port=8000)


def main():
    with RedisConnectionPool() as redis_pool:
        app = IssueManagementApp(redis_pool=redis_pool)
        app.run()


if __name__ == "__main__":
    if "--test" in sys.argv:
        print("Running doctests...")
        import doctest
        doctest.testmod()
    else:
        main()
