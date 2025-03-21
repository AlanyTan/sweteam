"""The Orchestrator agent logic
This is the agent to ensure every step follows software development process. 
The goal of this agent is not to innovate, rather, you check other agent's responses, and make sure they adhere to required process.
"""

import json
from re import A
from pydantic import BaseModel
from . import logger, config
from .utils import issue_manager
from .defs import BaseAgent, ollama_agent, openai_agent
from .defs.agent_defs import standard_tools, tool_instructions


class Orchestrator(BaseAgent):
    """The main orchestrator agent class
    This class is going to take initial user request, and collaborate with other
    agents using the issue_manager as media and try to make other agents follow the 
    software development process by reviewing the request, the issue ticket 
    and the response the agents provided. If needed the orchestrator will 
    as the agent to try again with certain requests.  And if the response is
    satisfactory, the orchestrator will ensure the issue ticket(s) are updated
    accordingly."""

    class BinaryAnswer(BaseModel):
        is_true: bool
        confidence_percentage: float
        exaplanation: str

    def is_true(self, question: str, usr_prompt: str = "", agt_response: str = "") -> BinaryAnswer:
        """
        Determine if the given response means a certain thing is true.

        Requires the LLM client to support structured response.

        Args:
            question (str): The question to be checked as True or False.
            usr_prompt (str): The prompt the user used to ask the agent to perform.
            agt_response (str): The response from the agent.

        Returns:
            bool: Whether the answer to the question is True.
        """

        self.logger.debug("Checking if %s is True for user prompt: %s and agent response: %s",
                          question, usr_prompt, agt_response)

        is_true_format = self.BinaryAnswer.model_json_schema()
        is_true_instruction = ("With the above message history, "
                               f"Using structured format, answer if '{question}' is True or False, "
                               f"from 0 to 100, how confident is your answer, and explain why.\n")

        message_history = []
        if usr_prompt:
            message_history.append({'role': 'user', 'content': usr_prompt})
        if agt_response:
            message_history.append({'role': 'assistant', 'content': agt_response})

        is_true_response = self.llm_client.chat(
            model=self.config.model,
            messages=[*message_history,
                      {'role': 'user',
                       'content': is_true_instruction}
                      ],
            format=is_true_format,
            options={
                'temperature': self.config.temperature}
        )
        if hasattr(is_true_response, 'message') and hasattr(is_true_response.message, 'content'):
            structrued_is_true_response = self.BinaryAnswer.model_validate_json(is_true_response.message.content)
        else:
            structrued_is_true_response = self.BinaryAnswer(is_true=False, confidence_level=0.0,
                                                            exaplanation="No response from LLM.")

        self.logger.debug("answer to the question: %r", structrued_is_true_response)

        return structrued_is_true_response

    class DistilledAnswer(BaseModel):
        answer: str
        explanation: str

    def distill(self, question: str = "", usr_prompt: str = "", agt_response: str = "") -> DistilledAnswer:
        """
        Convert the agent's response into a structured answer format.

        This function takes a question, the user's prompt, and the agent's response, and extracts a concise answer
        to the question from the agent's response. The answer is provided in a structured format with an explanation.

        Args:
            question (str): The question to be answered. Defaults to an empty string.
            usr_prompt (str): The user's prompt. Defaults to an empty string.
            agt_response (str): The agent's response. Defaults to an empty string.

        Returns:
            DistilledAnswer: An object containing the structured answer and an explanation.
        """

        self.logger.debug("Converting response to structured answer from agent..."
                          "Response: %s", agt_response)

        structured_answer_format = self.DistilledAnswer.model_json_schema()
        structured_answer_instruction = (f"Extract the concise answer to the question '{question}' from the user "
                                         "prompt and agent response. Provide the answer in a structured format with an explanation.\n")

        message_history = []
        if usr_prompt:
            message_history.append({'role': 'user', 'content': usr_prompt})
        if agt_response:
            message_history.append({'role': 'assistant', 'content': agt_response})

        structured_answer_response = self.llm_client.chat(
            model=self.config.model,
            messages=[*message_history,
                      {'role': 'user', 'content': structured_answer_instruction}],
            format=structured_answer_format,
            options={'temperature': self.config.temperature}
        )

        if hasattr(structured_answer_response, 'message') and hasattr(structured_answer_response.message, 'content'):
            structured_answer = self.DistilledAnswer.model_validate_json(structured_answer_response.message.content)
        else:
            structured_answer = self.DistilledAnswer(answer="", explanation="No response from LLM.")

        self.logger.debug("Structured answer: %r", structured_answer)

        return structured_answer

    class BreakdownAnswer(BaseModel):
        steps: list
        explanation: str

    def break_down(self, usr_prompt: str = "", agt_response: str = "") -> BreakdownAnswer:
        """
        Break down the agent's response into a structured format.

        This function takes the user's prompt and the agent's response, and transforms the agent's response
        into a structured format consisting of a list of steps and an explanation.

        Args:
            usr_prompt (str): The user's prompt. Defaults to an empty string.
            agt_response (str): The agent's response. Defaults to an empty string.

        Returns:
            BreakdownAnswer: An object containing the structured breakdown of the agent's response, 
                            including a list of steps and an explanation.
        """

        self.logger.debug("Breaking down response from agent..."
                          "Response: %s", agt_response)

        response_breakdown_format = self.BreakdownAnswer.model_json_schema()
        response_breakdown_instruction = (f"The assistant agent's response provided the following response, "
                                          f"please transform the response into a structured format of a list of steps: {agt_response}\n")
        breakdown_response = self.llm_client.chat(
            model=self.config.model,
            messages=[
                {'role': 'user', 'content': usr_prompt},
                {'role': 'assistant', 'content': agt_response},
                {'role': 'user', 'content': response_breakdown_instruction}
            ],
            format=response_breakdown_format,
            options={
                'temperature': self.config.temperature}
        )
        structured_breakdown_response = self.BreakdownAnswer.model_validate_json(breakdown_response.message.content)

        self.logger.debug("Structured breakdown response: %s", structured_breakdown_response.steps)
        self.logger.debug("Structured breakdown Explanation: %s", structured_breakdown_response.explanation)

        return structured_breakdown_response

    class ResponseEvaluation(BaseModel):
        score: float
        explanation: str

    def evalate_response(self, to_agt_prompt, agt_response: str, issue: dict) -> ResponseEvaluation:
        """Review the response from an agent and update the issue details accordingly.

        Args:
            to_agt_prompt (str): The response from the agent.
            agt_response (str): The response from the agent.
            issue (dict): The issue details.

        Returns:
            ResponseEvaluation: The updated issue details.
        """

        response_review_format = self.ResponseEvaluation.model_json_schema()
        response_review_instruction = ("Based on the provided user prompt and assistant response, "
                                       "How well did the assistant address the user request? "
                                       "Where a score of 0 means completely failure and a score of 10 means extremely well. "
                                       "Provide an explain the score.\n")
        review_response = self.llm_client.chat(
            model=self.config.model,
            messages=[
                {'role': 'user', 'content': to_agt_prompt},
                {'role': 'assistant', 'content': agt_response},
                {'role': 'user',
                    'content': response_review_instruction}
            ],
            format=response_review_format,
            options={
                'temperature': self.config.temperature}
        )
        if hasattr(review_response, 'message') and hasattr(review_response.message, 'content'):
            structrued_review_response = self.ResponseEvaluation.model_validate_json(review_response.message.content)
        else:
            structrued_review_response = self.ResponseEvaluation.model_validate_json(
                {"score": -1, "explanation": "evaluation failed to return a response."})

        self.logger.debug("Reviewing response from agent...")
        self.logger.debug("Response: %s", agt_response)
        self.logger.debug("Issue: %s", issue)

        return structrued_review_response

    def orchestrate(self, agent_names: list = []) -> None:
        """
        Follow up on open issues and assign them to appropriate agents.

        This method retrieves open issues, sorts them by priority and issue number, 
        and assigns them to agents based on their current status and assignee. 
        It also evaluates agent responses and updates issue details accordingly.

        Args:
            agents (list): List of agents to filter issues by assignee. 
                                If empty, all open issues are considered.
            issue_number (str): Specific issue number to filter open issues. 
                                If empty, all open issues are considered.

        Returns:
            None
        """
        def get_open_issues(issue_number: str = '') -> list[dict]:
            self.logger.debug(".get_open_issues(%s)...", issue_number)
            try:
                open_issues = self.issue_manager(
                    "list", issue=issue_number, only_in_state=["new", "in progress", "open"])
                self.logger.debug(
                    " the current list of open issues are %s", open_issues)
            except Exception as e:
                self.logger.error(" - Error loading open issues: %s", e)
                open_issues = []

            return open_issues if isinstance(open_issues, list) else [open_issues]

        agents: list[BaseAgent] = BaseAgent.instances(True)
        agent_roles = []
        for agt in agents:
            agent_roles.append((agt.name, self.distill("What is the role of the agent?", "",
                                                       agt.config.instruction).answer))

        # main orchestration loop
        retry_count = config.RETRY_COUNT
        while (retry_count := retry_count - 1) > 0:
            open_issues = get_open_issues()
            if not open_issues:
                new_request = self.get_human_input("\nNo open issues. What would you like the team to tackle next: \n")
                check_input = self.is_true(
                    "Does the user prompt look like a software development requirement?", new_request)
                if check_input.is_true:
                    self.logger.info("Creating a new issue: %s", new_request)
                    title = self.distill("Please summarize the following to create a title for this request?", "", new_request).answer
                    self.issue_manager("create", content={"title": title, "description":new_request})
                    open_issues = get_open_issues()
                else:
                    self.logger.warning(
                        'The user input """%s""" is not a valid software development request, because %s', new_request, check_input.exaplanation)
                    continue

            open_issues.sort(key=lambda x: [x.get("priority", "5"), tuple(
                map(int, x.get("issue", "").split("/")))])
            for open_issue in open_issues:
                issue_number = open_issue.get("issue")
                for agt in agents:
                    if agt.name == open_issue.get('assignee') != self.name:
                        break
                else:
                    self.logger.warning("No agent found with name %s", open_issue.get('assignee'))
                    # if not assigned, assigned to someone does not exist, or assigned to myself, try assign it
                    to_self_prompt = (f"Issue {issue_number} is assigned to {open_issue.get("assignee", "No One")},  "
                                      "which does not exist. Based on these roles descriptions, use the issue_manager tool "
                                      "action=assign to assign this issue to the most appropriate agent.\n"
                                      f"agent_roles: {agent_roles}."
                                      f"issue_manager() tool instruction: {tool_instructions['issue_manager']}")
                    o_reply = self.perform_task(
                        to_self_prompt, f"self({self.name})", context={'issue': self.issue_manager(action='read', issue=open_issue.get('issue'))})

                    # Issue re-assigned, Higher priority issue should be handled first, so break the loop
                    break
                
                to_agt_prompt = (f"Issue {issue_number} is assigned to you "
                f"and is in {open_issue.get('status')} status, it is about {open_issue.get('title')}. "
                "Please review the details of this issue using issue_manager and if it is specific enough to be coded, please write the code, "
                f"If you feel it is not clear and specific enough please analyze how to describe it in more details and create more specific sub issues for coding."
                )
                agt_reply = agt.perform_task(to_agt_prompt, self.name, 
                            context={'issue': self.issue_manager(action='read', issue=open_issue.get('issue'))})

                # Review the response
                response_evaluation = self.evalate_response(to_agt_prompt, str(agt_reply), open_issue)
                self.logger.debug("Review response: %s", response_evaluation)

                # should update feedback file here?

                if response_evaluation.score <= 5:
                    # was the response not satisfactory? have it re-done?
                    self.logger.warning(
                        "Agent %s response was not satisfactory, score: %s, agent_response: %s"
                        , agt.name, response_evaluation.score, agt_reply)
                    break

                ## check if the status of the issue is updated
                issue_updated = self.is_true(
                    f"Did agent {agt.name} update the issue ticket(s)?", to_agt_prompt, json.dumps(agt_reply))
                if issue_updated.is_true:
                    self.logger.info("Issue %s was updated by %s", issue_number, agt.name)
                else:
                    update_issue_prompt = (f"Please use issue_manager(action='update'...) to update issue "
                                           f"#{issue_number} according to assistant {agt.name} provided response:"
                                           f"{agt_reply}"
                                           )
                    update_issue_reply = self.perform_task(update_issue_prompt, self.name, 
                            context=[{'role': "user", 'content': str(self.issue_manager(action='read', issue=open_issue.get('issue')))},
                                        {'role': "user", 'content': to_agt_prompt}, 
                                        {'role': "assistant", 'content': agt_reply}])
                    issue_updated = self.is_true(
                        "Was the issue(s) updated successfully?", update_issue_prompt, json.dumps(update_issue_reply["content"]))
                    if issue_updated.is_true:
                        self.logger.info(
                            "Issue %s updated successfully.", issue_number)
                    else:
                        self.logger.warning(
                            "Failed to update Issue %s failed. Details: %s", issue_number, issue_updated.exaplanation)

                ## check if the response include code snipets, if so save them to files
                has_code_to_update = self.is_true(
                    "Does the response include code snippets?", to_agt_prompt, json.dumps(agt_reply))
                if has_code_to_update.is_true:
                    save_code_prompt = (f"The assistant {agt.name} provided code snippets in the response. "
                                        "Please evaluate if these code snippets should be saved into files to "
                                        f"become part of the software project to address issue {issue_number} "
                                        "If so, use apply_unified_diff() or overwrite_file() tool to save the code "
                                        "to the files meant for these code snipets to be saved in."
                                        f"if you are uncertain, use the dir_structure() tool to evaluate the current directory"
                                        f"and then use the chat_with_other_agent() tool to ask {agt.name} to provide the filenames for the code snipets."
                                        f"apply_unified_diff() tool instruction: {tool_instructions['apply_unified_diff']}"
                                        f"overwrite_file() tool instruction: {tool_instructions['overwrite_file']}"
                                        f"chat_with_other_agent() tool instruction: {tool_instructions['chat_with_other_agent']}"
                    )
                    save_code_reply = self.perform_task(save_code_prompt, self.name, 
                            context=[{'role': "user", 'content': str(self.issue_manager(action='read', issue=open_issue.get('issue')))},
                                        {'role': "user", 'content': to_agt_prompt}, 
                                        {'role': "assistant", 'content': agt_reply}])
                    code_saved = self.is_true(
                        "Was the code saved successfully?", save_code_prompt, save_code_reply["message"]["content"])
                    if code_saved.is_true:
                        self.logger.info("Code snippets saved successfully.")
                        # update the issue ticket to reflect this update
                        update_issue_prompt = (f"The code provided by agent {agt.name} have been saved, please "
                                                f"use issue_manager() tool to update issue {issue_number} or its "
                                                "sub-issues. Please include rationale of the change and brief "
                                                f"description of the change.")
                        update_issue_reply = self.perform_task(update_issue_prompt, self.name, 
                                context=[{'role': "user", 'content': str(self.issue_manager(action='read', issue=open_issue.get('issue')))},
                                            {'role': "user", 'content': to_agt_prompt}, 
                                            {'role': "assistant", 'content': agt_reply},
                                            {'role': "user", 'content': str(save_code_prompt)},
                                            {'role': "assistent", 'content': str(save_code_reply)}])
                    else:
                        self.logger.warning(
                            "Code snippets failed to save. Details: %s", code_saved.exaplanation)
                        

                # check the stage of the issue,
                # if stage is "plan", review if the issue is detailed enough to start coding, and break it down to steps and sub-issues
                # if stage is "coding", run the code of the updated file to check if it is working
                # if stage is "testing", run the main.py to check if the integration is working
                # if stage is "deploy", run the docker-compose to check if the code can be deployed properly
                stages = ["plan", "coding", "testing", "deploy"]
                issue_stage = self.distill(
                    f"Considering the content of issue #{issue_number}, which of the following stage is the issue in, {stages} ?"
                    , '', json.dumps(self.issue_manager(action='read', issue=issue_number)))

                match issue_stage.answer:
                    case "plan":
                        self.logger("Issue %s is in plan stage, need to break it down to steps and sub-issues.", issue_number)
                        pass
                    case "coding":
                        # test the updated file - run the code using execute_module()
                        pass
                    case "testing":
                        test_result = self.execute_command("bash", ["run.sh"])
                        to_self_prompt = (f"regarding issue {open_issue.get('issue')}, {agt.name} had responded with \"{agt_reply}\". And the current run.sh result is {test_result}."
                                        f"Use your file_search tool to check if the information provided in this reply exist in the issue files in your issues vector_store?"
                                        f"If not please use issue_manager() tool to update relevant issue or create sub issues under the most relevant issue."
                                        )
                        o_reply = self.perform_task(to_self_prompt, f"Orchestrator check if "
                                                    f"{agt.name} complete issue.", {"issue": open_issue.get('issue', 'generic')})
                        self.logger.debug(
                            f"<{self.name}> - Orchestrator self perform task update issue result:{o_reply}")

                    case "deploy":
                        # test the deployment - build docker, deploy to minikube, check the deployment
                        pass


                break

                
        open_issues = get_open_issues()
        if open_issues:
            self.logger.warning("Orchestrator tried %d times, but there are still open issues: %s.", config.RETRY_COUNT, open_issues)
        else:
            self.logger.info("Orchestrator successfully processed all open issues.")

        return get_open_issues()
        # print("***************")
        # for reply in replies:
        #     print(f"===")
        #     for entry in reply:
        #         print(entry.get("role").upper(), ":")
        #         print("  ", entry.get("content"))
        # while agt_to_eval := input("<<Eval>> Which agent would you like to evaluate (blank to skip eval)? "):
        #     eval_score = input(f"<<Eval>> How satisfied are you with the {agt_to_eval}? ")
        #     try:
        #         eval_score = int(eval_score)
        #     except:
        #         eval_score = 0
        #     eval_feedback = input(f"<<Eval>> How can the {agt_to_eval} improve in the future? ")
        #     self.evaluate_agent(agt_to_eval, eval_score, eval_feedback)
        # print("**********************")


class OllamaOrchestrator(ollama_agent.Ollama_Agent, Orchestrator):
    """the Orchestrator based on Ollama

    The Orchestrator needs to be a model that supports tools usage.
    It will evaluate the response from other agents, and update files if needed.
    """

    def __init__(self):
        self_config = self.AgentConfig({
            "name": "orchestrator",
            "use_tools": True,
            "tools": [],
            "model": "qwen2.5:14b",  # "qwq",
            "instruction": "You are an Orchestrator, you coordinate with other agents and ensure they follow their instructions. Sometimes, other agents may reply to your ask by giving you an answer as if this is a chat session, in those cases, they may provide you with markdown, including code snipets marks with ``` and ```, please help them save these answers to files according to the filenames specified in their answers.  Your main goal is to ensure the other agents' answer will result in useful file updates, if needed you help save their answers to the files using overwrite_file or ed_text_file tools.",
            "temperature": 0.1,
        })
        # Call the constructor of the base class
        super().__init__(agent_config=self_config)


class OpenAIOrchestrator(openai_agent.OpenAI_Agent, Orchestrator):
    """The Orchestrator
    Example::
        >>> with Orchestrator() as orchestrator:
        ...     orchestrator.name
        'orchestrator'

    """
    issue_vector_store = None

    def __init__(self):
        self_config = self.AgentConfig({
            "name": "orchestrator",
            "instruction": "You are an Orchestrator, you coordinate with other agents and ensure they follow their instructions. Sometimes, other agents may reply to your ask by giving you an answer as if this is a chat session, in those cases, they may provide you with markdown, including code snipets marks with ``` and ```, please help them save these answers to files according to the filenames specified in their answers.  Your main goal is to ensure the other agents' answer will result in useful file updates, if needed you help save their answers to the files using overwrite_file or ed_text_file tools.",
            "temperature": 0.5,
            "tools": [
                {"type": "file_search"}
            ]
        })
        # Call the constructor of the base class
        super().__init__(agent_config=self_config)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.issue_vector_store:
            self.llm_client.beta.vector_stores.delete(
                self.issue_vector_store.id)
        try:
            existing_vector_stores = self.llm_client.beta.vector_stores.list()
            for vs in [vs for vs in existing_vector_stores.data if vs.name == "issues"]:
                try:
                    self.llm_client.beta.vector_stores.delete(vs.id)
                except Exception as err:
                    logger.warning(
                        f"<{self.name}> - Orchestrator trying to delete vector_store {vs.id} received Error: {err}")
        except Exception as e:
            logger.warning(
                f"<{self.name}> - Orchestrator trying to remove vector store received Error: {e}", exc_info=e)
        try:
            # for agt in agents:
            #     self.llm_client.beta.assistants.delete(agt.assistant.id)
            existing_assistants = self.llm_client.beta.assistants.list()
            for ast in [ast for ast in existing_assistants.data if ast.name in [agt.name for agt in BaseAgent.instances(True)]]:
                try:
                    self.llm_client.beta.assistants.delete(ast.id)
                except Exception as err:
                    logger.warning(
                        f"<{self.name}> - Orchestrator trying to remove assistant {ast.name}, received Error: {err}")
            for f in self.llm_client.files.list().data:
                self.llm_client.files.delete(f.id)
        except Exception as e:
            logger.error(
                f"<{self.name}> - Orchestrator trying to find and remove orphan assistants, received Error: {e}", exc_info=e)
        super().__exit__(exc_type, exc_val, exc_tb)

class OrchestratorFactory(Orchestrator):
    @staticmethod
    def create(type: str):
        if type == "ollama":
            return OllamaOrchestrator()
        elif type == "openai":
            return OpenAIOrchestrator()
        else:
            raise ValueError("Agent type %s not recognized.", type)

if __name__ == "__main__":
    import doctest
    doctest.testmod()
