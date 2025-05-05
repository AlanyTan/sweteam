"""module script to be used when utils is called directly at cli"""
import json
import os
import sys
from . import dir_structure, issue_manager
from .log import logger
from .initialize_project import initialize_agent_files


def test() -> None:
    import doctest
    doctest.testmod()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        match sys.argv[1]:
            case "update_agents":
                if os.path.exists(os.path.join(os.getcwd(), "agents")):
                    agent_parent_dir = os.getcwd()
                else:
                    agent_parent_dir = os.path.dirname(
                        os.path.dirname(__file__))

                print("local run of util on " + agent_parent_dir)

                initialize_agent_files(agent_parent_dir)
                sys.exit(0)
            case "issue_manager":
                issman_args = {}
                only_in_state = []
                try:
                    issman_args["action"] = sys.argv[2]
                    for i in range(3, len(sys.argv)):
                        if sys.argv[i].startswith("content="):
                            issman_args["content"] = sys.argv[i].removeprefix(
                                "content=")
                        if sys.argv[i].startswith("only_in_state"):
                            issman_args["only_in_state"] = sys.argv[i].removeprefix(
                                "only_in_state=").split(",")
                        if sys.argv[i].startswith("issue="):
                            issman_args["issue"] = sys.argv[i].removeprefix(
                                ("issue="))
                        if sys.argv[i].startswith("assignee="):
                            issman_args["assignee"] = sys.argv[i].removeprefix(
                                ("assignee="))
                    issue_result = issue_manager(**issman_args)
                    if isinstance(issue_result, list):
                        issue_result.sort(key=lambda x: tuple(
                            map(int, x.get("issue").split("/"))))
                    for key_ in issue_result:
                        if isinstance(key_, str):
                            if key_ == "updates":
                                print(f"{key_.upper()}:")
                                for upd in issue_result[key_]:
                                    upd_len = len(upd)
                                    for seq, key in enumerate(upd):
                                        match seq:
                                            case 0:
                                                border_char = f"{0x2514:c}{0x252c:c}{0x2500:c}"
                                            case n if n == upd_len - 1:
                                                border_char = f"{0x2514:c}{0x2500:c}"
                                            case _:
                                                border_char = f"{0x251c:c}{0x2500:c}"
                                        print(f"    {border_char}\t{key.capitalize()}: {upd[key]}")
                            else:
                                print(f"{key_.upper()}: {issue_result[key_]}")
                        else:
                            print("-", end="")
                            for key in key_:
                                print(f" {key:7}: {key_[key]:11}", end=" ")
                            print("\t")
                except Exception as e:
                    logger.error(f"Error processing issue_manager request: {e}, at line {e.__traceback__.tb_lineno}")
                    print(f"Usage: python -m {os.path.basename(__file__)} issue_manager list|read|update|create [issue='1/1'] [only_in_state='new,in progress'] [content='json str of an issue update']")
                sys.exit(0)
            case "dir_structure":
                dir_structure_args = {}
                for i in range(2, len(sys.argv)):
                    if sys.argv[i].startswith("actual_only="):
                        dir_structure_args["actual_only"] = sys.argv[i].removeprefix(
                            "actual_only=") == "True"
                    elif sys.argv[i].startswith("output_format="):
                        dir_structure_args["output_format"] = sys.argv[i].removeprefix(
                            "output_format=")
                    else:
                        dir_structure_args["path"] = sys.argv[i]

                print(dir_structure(**dir_structure_args))

                sys.exit(0)
            case "test":
                test()
                sys.exit(0)
            case _ as wrong_arg:
                logger.warning(f"{wrong_arg} is not a valid option")

    print(f"Usage: python -m {os.path.basename(__file__)} [test|update_agents|issue_manager|dir_structure]")
