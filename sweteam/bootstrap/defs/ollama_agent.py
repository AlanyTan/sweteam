"""Ollama Agent, won't use until local model are possible."""
import json
import os
import re
import yaml
import ollama
from datetime import datetime
from typing import Sequence, Self, List, Dict
from ..config import config
from ..utils import issue_manager, dir_structure, execute_module, execute_command
from .agent_defs import standard_tools
from . import msg_logger, BaseAgent
from pydantic import BaseModel


class Ollama_Agent(BaseAgent):
    """
    Ollama_Agent is a specialized agent that interacts with the Ollama LLM client.

    This agent is capable of performing tasks, evaluating other agents, and 
    communicating with other agents. It supports the use of tools and maintains 
    a conversation history. The agent can be initialized with a specific configuration 
    and can manage its lifecycle using context management.

    Attributes:
        config (AgentConfig): Configuration for the agent.
        llm_client (ollama.Client): The LLM client used for communication.
        messages (list): The conversation history.
        model_initialized (bool): Indicates if the model has been initialized.
        tools (list): List of tools available to the agent.

    Methods:
        __enter__(): Initializes the agent model if not already initialized.
        __exit__(exc_type, exc_val, exc_tb): Cleans up resources when the agent is no longer needed.
        perform_task(task, from_, context): Performs a task and returns the result.
        evaluate_agent(agent_name, score, additional_instructions): Evaluates the performance of another agent.
        chat_with_other_agent(agent_name, message, issue): Communicates with another agent.
    """

    class TaskResult(BaseModel):
        role: str = 'assistant'
        content: str
        images: List[str] | None = None
        tool_calls: List[Dict[str, str]] | None = None
        tool_used: List[Dict[str, str]] | None = None

    def __init__(self, agent_config: BaseAgent.AgentConfig = {}) -> None:
        # use agent_config
        agent_config_dict = agent_config.to_dict()
        agent_config_dict.setdefault("model", agent_config_dict.get("model") or
                                     config.OLLAMA_DEFAULT_BASE_MODEL)
        agent_config_dict.setdefault("name", agent_config_dict.get(
            "name", "noname").replace(" ", "_"))
        super().__init__(agent_config_dict.get("name"))
        self.config = self.AgentConfig(agent_config_dict)
        self.logger.debug("loaded agent %s config from parameter agent_config: %s as %s",
                          self.name, agent_config, self.config)

        self.llm_client: ollama.Client = ollama.Client(host=config.OLLAMA_URL)

        if self.config.use_tools:
            self.tools = self.config.tools
            self.tools.extend(standard_tools)
        else:
            self.tools = []

        # Initialize conversation with a user query
        self.messages = []
        self.model_initialized = False
        self.logger.info("Initializing agent %s", self.name)

    def __enter__(self) -> Self:
        if self.model_initialized:
            return self
        existing_models = self.llm_client.list()
        for model in existing_models.get("models", []):
            model_name = model.get("name") or model.get("model")
            if model_name.partition(":")[0] == self.config.name:
                self.logger.debug(f"found existing model {self.name}")
                break
        else:
            # Note that Ollama uses "model" property to represent roughly an "agent" concept
            # the model name represents an object that is of a certain model type with initial system prompt
            # so the model name in Ollama is not the model type, rather it's an entity that includes system prompt
            response = self.llm_client.create(
                model=self.name,
                from_=self.config.model, system=self.config.instruction,
                parameters={"temperature": self.config.temperature},
                stream=False)
            self.logger.info("created ollama model %s received %s", self.name, response)
        self.model_initialized = True

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.debug(f"<{self.name}> - Exiting agent ...")
        if not self.llm_client is None:
            try:
                self.llm_client.delete(self.name)
            except Exception as e:
                self.logger.warning(
                    f"<{self.name}> - deleting thread received Error: {e}")

    def __str__(self) -> str:
        """Allow printing of myself (source code)

        """
        return f"<Agent: {self.name}>"

    class MessageHistory(BaseModel):
        role: str
        content: str | dict

    def messages_append(self, new_message: MessageHistory, msg_hist_object: list[MessageHistory] = []) -> None:
        def msg_len(msg) -> int:
            try:
                return len(json.dumps(msg))
            except Exception as e:
                # self.logger.warning("Error calculating message length: %s", e)
                return len(repr(msg))

        byte_to_token_ratio = 6  # roughly 4 bytes per token with 50% overhead so set it to 6 to be safe

        if 'tool_calls' in new_message and new_message['tool_calls']:
            for idx, tool_call in enumerate(new_message['tool_calls']):
                new_message[idx] = tool_call.dict()

        if msg_hist_object is self.messages:
            msg_hist_object = []

        for hist_obj in [self.messages, msg_hist_object]:
            hist_obj.append(new_message)
            while msg_len(hist_obj) > self.config.context_window_size / byte_to_token_ratio * 1024:
                del hist_obj[0]

    def perform_task(self, task: str = '', from_: str = "Unknown", context: list[MessageHistory] | str = '') -> TaskResult:
        """Chat with this agent and call tools if the agent asks to do so.
        Args:
            task: the prompt describing a task for this agent to perform
            from_: the name of the party that initiated the task
            context: the context of the task - can be either a list of historical messages or a string
                     if a string is provided, it will be added to the context as a user message
        Returns:
            TaskResult: the result of the task - it's a structure that is compatible with the LLM message class 
                        with an added property tool_used that contains the tool calls used by the agent and their return
        """
        self.__enter__()
        tool_used = []
        response = None
        msg_logger.info("%s >> %s - %s (use tools=%s)",
                        from_, self.name, task, bool(self.tools))
        self.logger.info("%s >> %s - %s (use tools=%s)",
                         from_, self.name, task, bool(self.tools))
        func_names = [item['function']['name']
                      for item in self.tools if item['type'] == "function"]

        if (isinstance(context, list) and [True for m in context if isinstance(m, self.MessageHistory)]):
            task_messages = context
        elif isinstance(context, str):
            task_messages = [{'role': 'user', 'content': f"Given the following context: {context}"}]
        elif context:
            task_messages = [
                {'role': 'user', 'content': f"Considering the following structured context: {json.dumps(context)}"}]
        else:
            task_messages = self.messages

        self.messages_append({'role': 'user', 'content': f"Please do the following: {task}"},
                             msg_hist_object=task_messages)

        while self.tools or response is None:
            response = self.llm_client.chat(
                model=self.name, messages=task_messages, tools=(self.tools if self.config.use_tools else None))

            # Add the model's response to the conversation history
            self.messages_append(dict(response['message']), msg_hist_object=task_messages)

            # Process function calls made by the model
            if response['message'].get('tool_calls'):
                self.logger.debug("<%s> The session is trying to use tools: %s",
                                  self.name, response['message']['tool_calls'])

                for tool in response['message']['tool_calls']:
                    arguments = tool['function']['arguments']
                    func_name = tool['function']['name']
                    if func_name in func_names:
                        func = getattr(self, func_name, None)
                        try:
                            function_response = func(
                                **arguments) if func else f"Error {func_name} is configured as a tool but is not a method I have."
                            self.logger.debug(
                                "calling <%s> returned: %s", func_name, function_response)
                        except Exception as e:
                            function_response = f"calling {func_name} failed with Error: {e!r}"
                            self.logger.error(
                                "calling <%s(%s)> run into Error: %s", func_name, arguments, e, exc_info=e)
                        # Add function response to the conversation
                        self.messages_append(
                            {
                                'role': 'tool',
                                'content': repr(function_response),
                            }, msg_hist_object=task_messages
                        )
                        tool_used.append({
                            "sequence_no": len(tool_used) + 1,
                            "tool_type": "function",
                            "tool_name": func_name,
                            "tool_return": str(function_response)
                        })
                    else:
                        self.messages_append(
                            {
                                'role': 'tool',
                                'content': f"{func_name} is not a configured tool."
                            }, msg_hist_object=task_messages
                        )
            else:
                break

            self.logger.debug(
                "partial_response: %s", response['message'])

        else:
            self.logger.debug("The session didn't use tools. ")

        final_message = dict(response['message'])
        final_message['content'] = re.sub(r'<(think|thinking)>.*?</\1>', '', final_message['content'], flags=re.DOTALL)
        final_message['tool_used'] = tool_used
        if 'tool_calls' in final_message and final_message['tool_calls']:
            for idx, tool_call in enumerate(final_message['tool_calls']):
                final_message['tool_calls'][idx] = tool_call.dict()
        self.logger.debug("final response: %s", final_message)

        return final_message

    def evaluate_agent(self, agent_name: str, score: int = 0, additional_instructions: str = "") -> str:
        """Provide evaluation of the response by an agent
        Args:
            agent_name: the name of the agent to evaluate
            score: positive if agent response meet expectation, netagive if did not
            additional_instructions: how can the agent improve in the future
        Returns:
            status of the evaluation
        """
        return "evaluation is temporarily disabled"
        self.logger.debug(
            f"<{self.name}> - evaluate_agent({agent_name},{score},{additional_instructions})")
        other_agents = [a for a in BaseAgent.instances(
            True) if a.name == agent_name]
        if other_agents:
            the_other_agent = other_agents[0]
        else:
            self.logger.warning(
                f"<{self.name}> - evaluate_agent does not recognize {agent_name} as a valid agent.")
            return f"<{self.name}> - evaluate_agent does not recognize {agent_name} as a valid agent."
        if the_other_agent:
            the_other_agent.performance_factor *= 1 + max(score, 10) / 100
            if additional_instructions:
                the_other_agent.additional_instructions = additional_instructions
            agent_dir = os.path.join(os.path.dirname(__file__), "agents")
            new_eval = {"timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f"),
                        "evaluated by": self.name,
                        "score": score,
                        "additional_instructions": additional_instructions
                        }
            new_eval_yaml = yaml.dump(
                [new_eval], default_flow_style=False, sort_keys=False)
            with open(os.path.join(agent_dir, agent_name + ".feedback.yaml"), 'a+') as yamlfile:
                yamlfile.write("\n" + new_eval_yaml)
            self.logger.debug(f"<{self.name}> - evaluate_agent, agent {agent_name}"
                              f" new performance score is {the_other_agent.performance_factor}.")
            return "Thanks for your feedback"
        else:
            self.logger.warning(f"<{self.name}> - evaluate_agent, unknown agent "
                                f"{agent_name}, can't evaluate, skipping...")
            return f"Agent {agent_name} was not found, can't evaluate."

    def chat_with_other_agent(self, agent_name: str, message: str, issue: str = '') -> str:
        """Chat with another agent

        Args:
            agent_name: the name of the agent to chat with
            message: the message to send to the agent

        Returns:
            str: the response from the agent
        """
        self.logger.debug(
            f"<{self.name}> - chat_with_other_agent({agent_name},{message},{issue})")
        for the_other_agent in [a for a in BaseAgent.instances(True) if a.name == agent_name]:
            chat_result = the_other_agent.perform_task(
                message, self.name, context=self.messages)
            return f"{agent_name} replied: {chat_result.get('respons')}.  {chat_result.get('tool_use')!r}"
        else:
            raise Exception(f"chat_with_other_agent cannot find agent_name={agent_name}, "
                            "please make sure the other agent you want to chat with exist in the agent_roles list.")


def test():
    with Ollama_Agent("test_agent", agent_config={"base_model": "llama3.2",
                                                  "instruction": "",
                                                  "temperature": 0.25,
                                                  "name": "test_agent",
                                                  "tools": [{
                                                      "type": "function",
                                                      "function": {
                                                          "name": "dir_structure",
                                                          "description": "Return or update project directory structure and plan.",
                                                          "parameters": {
                                                              "type": "object",
                                                              "properties": {
                                                                 "action": {
                                                                     "type": "string",
                                                                     "description": "'read' or 'update'. Default is 'read', will return project directory structure compare to the planned structure; if 'update', will update the plan to include new proposed directories and files in the plan, but will not create the directory and files until apply_unified_diff or overwrite_file are called."
                                                                 },
                                                                  "path": {
                                                                     "type": "object",
                                                                     "description": "if action is update, an object representing the planned dir structure, "
                                                                 },
                                                                  "actual_only": {
                                                                     "type": "boolean",
                                                                     "description": "default is False, will return planned and actual dir_structure, showing discrepencies; If True, will only return actual created dir and files."
                                                                 },
                                                                  "output_format": {
                                                                     "type": "string",
                                                                     "description": "output format, default is YAML will return full dir structure as an YAML object including metadata of files like type, description, size; if is 'csv', it will return file_path, file_description in csv format."
                                                                 }
                                                              }
                                                          }
                                                      }
                                                  }]
                                                  }) as test_agent:
        test_agent.perform_task(
            input("what do you want to say to the test_agent:"))


if __name__ == "__main__":
    # testing locally
    test()
