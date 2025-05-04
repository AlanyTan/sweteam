from abc import ABC, abstractmethod
import json
import os
import re
from ollama import ChatResponse
from pydantic import BaseModel
from ..utils import issue_manager, dir_structure, execute_command, execute_module
from ..utils.log import get_logger


class BaseAgent(ABC):
    _instances = []

    class AgentConfig:
        model = "mistral-nemo:latest"
        type = "ollama"
        instruction: str = ""
        additional_instructions: str = ""
        temperature: int = 1
        tools: list = []
        tool_choice: str | dict = "auto"
        evaluation_criteria: str = ""
        use_tools: bool = False
        context_window_size: int = 128
        name: str = ''

        def __init__(self, initial_values: dict = {}) -> None:
            for key, value in initial_values.items():
                setattr(self, key, value)

        def __repr__(self) -> str:
            attrs = ', '.join(f"{key}={value!r}" for key,
                              value in self.__dict__.items())
            return f"{self.__class__.__name__}({attrs})"

        def to_dict(self) -> dict:
            return self.__dict__

    class Message(BaseModel):
        role: str  # e.g., "system", "user", "assistant"
        content: str

    class Response(BaseModel):
        message: 'BaseAgent.Message'

    class LLMClient(ABC):
        @abstractmethod
        def chat(self, messages: list, **kwargs) -> 'BaseAgent.Response':
            """Abstract chat method.

            Args:
                messages (list): A list of messages comprising the conversation.
                **kwargs: Additional keyword arguments for specific LLM client implementations.

            Returns:
                dict: The chat response from the LLM.
            """
            raise NotImplementedError

        @abstractmethod
        def generate(self, prompt: str, **kwargs) -> dict:
            """Abstract text generation method.

            Args:
                prompt (str): The text prompt for generation.
                **kwargs: Additional keyword arguments for specific LLM client implementations.

            Returns:
                dict: The generation response from the LLM.
            """
            raise NotImplementedError

        @abstractmethod
        def list(self, **kwargs) -> list:  # Or dict, adjust as needed
            """Abstract method to list available models.

            Args:
                **kwargs: Additional keyword arguments for specific LLM client implementations.

            Returns:
                list or dict:  A list or dictionary of available models.
            """
            raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.config!r})"

    def __init__(self, agent_name: str = '') -> None:
        self.name = agent_name
        self.config = self.AgentConfig()
        self.llm_client: BaseAgent.LLMClient
        self.logger = get_logger(
            f'{self.__class__.__name__ or ""}[{self.name}]')
        self.__class__._instances.append(self)

    @classmethod
    def instances(cls, include_children: bool = True) -> list:
        if include_children:
            temp_instances = set()
            # Iterate through all direct child classes
            for subclass in cls.__subclasses__():
                if hasattr(subclass, '_instances'):
                    temp_instances.update(subclass._instances)
            # Include instances of the current class as well
            if hasattr(cls, '_instances'):
                temp_instances.update(cls._instances)
            return list(temp_instances)
        else:
            return cls._instances  # Return the list of all instances for this class

    # method to list/read/write issues
    def issue_manager(self, action: str, issue: str = '',
                      only_in_state: list = [], content: str = None,
                      assignee: str = None):
        return issue_manager(action, issue, only_in_state, content, assignee, caller=self.name)

    def dir_structure(self, action: str = 'read', path: dict = {}) -> str:
        """update or return project directory structure

        Args:
            action - one of read|delete|update
        """
        self.logger.debug(
            f"<{self.name}> - calling dir_structure({action=}, {path=})")
        return dir_structure(action=action, path=path)

    def execute_command(self, *args, **kwargs) -> str:
        """"""
        self.logger.debug(
            f"<{self.name}> - calling execute_command with {kwargs}")
        return execute_command(*args, **kwargs)

    def execute_module(self, *args, **kwargs) -> str:
        self.logger.debug(
            f"<{self.name}> - calling execute_module with {kwargs}")
        return execute_module(*args, **kwargs)

    def read_file(self, filepath: str = '') -> str:
        """Return the content of a given file.

        Args:
            filepath (str, optional): The name of the file to be read. Defaults to None, which means read my own code

        Returns:
            str: The json dumps of the {filepath: filepath, content: content} dictionary. 
            If there is an error, the json dumps of {filepath: filepath, error: error} of the file.

        Raises:
            Exception: If there is an error reading the file.

        Example::
            >>> agent = OpenAI_Agent("pm")
            >>> print(agent.read_file("non-existant.file"))
            {"filepath": "non-existant.file", "error": "[Errno 2] No such file or directory: 'non-existant.file'"}
        """
        if not filepath:
            filepath = __file__

        self.logger.debug(f"<{self.name}> - read_file {filepath}")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            self.logger.info(
                "read_file %s successfully.", filepath)
            result = {
                'filepath': filepath,
                'content': content,
            }
        except Exception as e:
            self.logger.warning(
                "read_file Failed to read file %s", filepath, exc_info=e)
            content = f"{e}"
            result = {
                'filepath': filepath,
                'error': f"{e}",
            }
        return json.dumps(result)

    def overwrite_file(self, filename: str, content: str, force: bool = False) -> str:
        """Write content info to a file, mostly used for binary files

        Args:
            filepath (str): The name of the file to write to
            content (str): The text to write to the file

        Returns:
            str: A message indicating success or failure

        Example::
            >>> agent = OpenAI_Agent("pm")
            >>> print(agent.overwrite_file("deleteme.test", "This is a test, please delete me.", force=True))
            File deleteme.test has been written successfully.
        """
        self.logger.debug(
            "%swriting file %s with content %s", "over" if force else '', filename, content)

        if not os.path.exists(filename) or force:
            try:
                directory = os.path.dirname(filename)
                if directory:
                    os.makedirs(directory, exist_ok=True)

                with open(filename, 'w', encoding="utf-8") as f:
                    f.write(content)

                self.logger.info(
                    "overwrite_file %s successfully.", filename)
                result = f"File {filename} has been written successfully."
            except Exception as e:
                self.logger.error(
                    "overwrite_file Failed to write to file %s", filename, exc_info=e)
                result = f"Error overwriting file {filename} due to: {str(e)} __details__ {e}"
        else:
            result = f"file {filename} already exists, please review its content at the end of this message. "
            "if you are certain your proposed change will not break things, you can then use "
            f"`force=True` to overwrite the existing content: <{self.read_file(filename)}>"

        return result

    def apply_unified_diff_to_file(self, filepath: str, diffs: str) -> str:
        """accept unified diff hunks and apply to filepath

        Args:
            filepath - filepath to the original file of which content needs to be updated
            diffs - text of unified diff instructions

        Returns:
            str message of if update was successful.
                Example::
        >>> agent = OpenAI_Agent("pm")
        >>> agent.apply_unified_diff("delete.me", "--- delete.me 2022-02-02 02:02:02\\n+++ new_delete.me 2023-03-03 03:03:03\\n@@ -1,5 +1,5 @@\\n+Line1\\n+Lin2\\n+Line3\\n+Line4\\n+Line5")
        'Successfully updated delete.me.'
        """
        def parse_hunk_header(header) -> tuple[int, int, int, int]:
            # Use regex to correctly parse the hunk header
            match = re.match(
                r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', header)
            if not match:
                raise ValueError(f"Invalid hunk header: {header}")

            old_start = max(int(match.group(1)) - 1, 0)
            # Default to 1 if count is not specified
            old_count = int(match.group(2) or 1)
            new_start = max(int(match.group(3)) - 1, 0)
            # Default to 1 if count is not specified
            new_count = int(match.group(4) or 1)

            return old_start, old_count, new_start, new_count

        original_lines = []
        if os.path.exists(filepath):
            self.logger.debug(f"<{self.name}> - apply_unified_diff() file "
                              f"{filepath} already exists, "
                              "reading in to be changed")
            with open(filepath, "r", encoding="utf-8") as f:
                original_lines = f.readlines()

        updated_lines = original_lines[:]
        update_offset = orig_start = orig_line_cnt = upd_start = upd_line_cnt = 0
        orig_hunk_line_cnt = upd_hunk_line_cnt = 0
        # Skip the file header lines
        diff_lines = (line for line in diffs.splitlines(keepends=True)
                      if not line.startswith(("---", "+++", "diff --git", "new file mode", "index ")))
        for diff_line in diff_lines:
            if diff_line.startswith('@@'):
                orig_start, orig_line_cnt, upd_start, upd_line_cnt = parse_hunk_header(
                    diff_line)
                orig_hunk_line_cnt = upd_hunk_line_cnt = 0
            elif diff_line.startswith('-'):
                # Removal
                line_num = orig_start + update_offset
                if original_lines[line_num:line_num + 1] != [diff_line[1:]]:
                    raise ValueError(f"Can't Delete, Orig_file line #{orig_start + 1} does "
                                     f"not match diff hunk '{
                                         diff_line.strip()}'."
                                     "Try read the content of the file again "
                                     "so you can recreate correct unified diffs.")
                del updated_lines[line_num]
                update_offset -= 1
                orig_hunk_line_cnt += 1
            elif diff_line.startswith('+'):
                # Addition
                line_num = orig_start + update_offset
                updated_lines.insert(line_num, diff_line[1:])
                update_offset += 1
                upd_hunk_line_cnt += 1
            elif diff_line.startswith(' '):
                # Context line
                line_num = orig_start + update_offset
                if updated_lines[line_num:line_num + 1] != [diff_line]:
                    raise ValueError(f"Can't find expected context, "
                                     f"Orig_file line #{line_num + 1} does "
                                     f"not match diff hunk '{diff_line}'."
                                     "Try read the content of the file again "
                                     "so you can recreate correct unified diffs.")
                orig_hunk_line_cnt += 1
                upd_hunk_line_cnt += 1
            else:
                raise ValueError(f"Unexpected diff hunk specification line: "
                                 f"'{diff_line.strip()}'.  Please use strict "
                                 "Unified Diff syntax to specify diffs.")
        if orig_hunk_line_cnt != orig_line_cnt or upd_hunk_line_cnt != upd_line_cnt:
            raise ValueError(f"UniDiff specification invalid, hunk specified "
                             f"{orig_line_cnt} original lines and {upd_line_cnt}"
                             f" updated lines, but the hunk commands were for "
                             f"{orig_hunk_line_cnt} original lines and "
                             f"{upd_hunk_line_cnt} updated lines.")
        self.logger.debug(f"<{self.name}> - apply_unified_diff() writing to file "
                          f"{filepath} ...")

        directory = os.path.dirname(filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)

        return f"Successfully updated {filepath}."

    @abstractmethod
    def perform_task(self, task: str = None, from_: str = "Unknown", context: dict = {}) -> str:
        raise NotImplementedError

    @abstractmethod
    def evaluate_agent(self, agent_name: str, score: int = 0, additional_instructions: str = "") -> str:
        raise NotImplementedError

    @abstractmethod
    def chat_with_other_agent(self, agent_name: str, message: str, issue: str = '') -> str:
        raise NotImplementedError

    def get_human_input(self, prompt: str = None) -> str:
        """Help AI get user input

        Args:
            prompt: the message shows to the user regarding what the question is about.

        Returns:
            str that the user entered into the input() function
        """
        self.logger.debug(f"<{self.name}> - get_human_input({prompt})")
        if prompt:
            result = input(
                f"\n***************<{self.name}> Needs User Input***************\n{prompt}:")
        else:
            result = input("The AI needs some input from you:")
        return result


class AgentFactory:
    @staticmethod
    def create(agent_config: BaseAgent.AgentConfig, previous_feedback: dict = {}) -> BaseAgent:
        """Create an agent based on the agent_config

        Args:
            agent_config: The configuration of the agent to be created

        Returns:
            BaseAgent: The created agent
        """
        match agent_config.type.lower():
            case "ollama":
                from .ollama_agent import Ollama_Agent
                return Ollama_Agent(agent_config=agent_config)
            case "openai":
                from .openai_agent import OpenAI_Agent
                return OpenAI_Agent(agent_config=agent_config)
            case _:
                raise ValueError(f"Unknown engine type: {agent_config.type}")
