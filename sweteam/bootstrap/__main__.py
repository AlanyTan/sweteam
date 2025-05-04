"""initialize a software development project
This is the __main__ file belonging to the bootstrap module. Which is used to kick of a new project.
It is responsible for creating the project directory and initializing it with bootstrap code.

Usage:
    python __main__.py [-p <project_name>] [-n]
    <project_name> is the name of the new project, default project name is "default", or can be set by PROJECT_NAME environment variable.
    -n means start over, it will delete the existing "team" of agents for the project and copy the bootstrap agents over.

"""
import contextlib
from datetime import datetime
import json
import os
import sys
import shutil
import subprocess
import yaml

from . import utils, logging, logger
from .config import config
from .defs import AgentFactory, BaseAgent
from .utils.log import logging_context
from .orchestrator import OrchestratorFactory, Orchestrator


def main():
    from .orchestrator import OllamaOrchestrator as Orchestrator
    orchestrator: Orchestrator
    if __package__ and __package__.endswith("bootstrap"):
        print(f"Warning, Current package name: {__package__}")
    agents_dir = os.path.join(os.path.dirname(__file__), 'agents')
    logger.debug(f"package name: {__package__}")
    agents_list = [entry.removesuffix(".json") for entry in os.listdir(
        agents_dir) if entry.endswith(".json")]
    with OrchestratorFactory.create(type="ollama") as orchestrator:
        with contextlib.ExitStack() as stack:
            for agt in agents_list:
                agt_cfg: BaseAgent.AgentConfig
                try:
                    agt_cfg = BaseAgent.AgentConfig(json.load(
                        open(os.path.join(agents_dir, agt + ".json"))))
                    logger.debug("loaded agent %s: %s", agt, agt_cfg)
                except Exception as e:
                    logger.error(
                        "Error loading agent config %s: %s", agt, e, exc_info=e)
                    continue

                try:
                    feedback_file = os.path.join(agents_dir, agt + ".feedback.yaml")
                    if os.path.exists(feedback_file) and os.path.isfile(feedback_file):
                        agt_feedback = yaml.safe_load(
                            open(feedback_file))
                        logger.debug("loaded agent %s feedback: %s",
                                     agt, agt_feedback)
                    else:
                        agt_feedback = None
                        logger.warning("No feedback file found for agent %s", agt)
                except Exception as e:
                    logger.warning(
                        "Error loading agent feedback %s: %s", agt, e, exc_info=e)
                    agt_feedback = None

                stack.enter_context(AgentFactory.create(
                    agent_config=agt_cfg, previous_feedback=agt_feedback))
            try:
                orchestrator.orchestrate()
            except Exception as e:
                logger.fatal("SWE Team run into error that can't be recovered, shuting down...", exc_info=e)

            logger.info(f"Exiting all agents...")
    logger.info(f"Exiting Done")


def create_project(project_name: str = 'default_project', overwrite: bool = False) -> None:
    """
    Creates and initializes a new software development project with bootstrap code and development team setup.

    This function performs the following tasks:
    1. Creates a new project directory with the specified name
    2. Initializes a new git branch for the project
    3. Sets up uv project configuration
    4. Copies bootstrap code and agent files
    5. Initializes Docker configuration
    6. Sets up project structure and startup scripts
    7. Launches the development team agents

    Args:
        project_name (str): Name of the project to create. Defaults to 'default_project'.
        overwrite (bool): If True, deletes existing project files and reinitializes.
                     If False, preserves existing files. Defaults to False.

    Returns:
        None

    Raises:
        FileExistsError: If project directory exists and overwrite is False
        FileNotFoundError: If git is not installed on the system
        subprocess.CalledProcessError: If uv or git commands fail
        Exception: For other initialization errors
    """
    EMBEDDED_DEV_TEAM_NAME = "embedded_dev_team"
    new_branch_name = ''
    try:
        current_file = os.path.realpath(__file__)
        current_dir = os.path.dirname(current_file)
        current_parent_dir = os.path.dirname(current_dir)
        project_dir = os.path.join(os.getcwd(), project_name)
        parent_dir = os.path.dirname(project_dir)
        project_team_dir = os.path.join(
            project_dir, EMBEDDED_DEV_TEAM_NAME)
        try:
            current_git_branch = subprocess.run(
                ['git', 'branch', '--show-current'], capture_output=True, text=True, check=True).stdout.strip()
            logger.debug(f"Currently on branch {current_git_branch}")
            if (current_git_branch in ["main", "master"]):
                old_branch_name = current_git_branch
                logger.warning(f"??Currently on branch <"
                               f"{current_git_branch}>, we shall never "
                               "change it without a PR. creating new branch...")
                all_branches = subprocess.run(
                    ['git', 'branch', '--list'], capture_output=True, text=True).stdout
                new_branch_name = f"{
                    project_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                if new_branch_name in [branch_name.strip() for branch_name in all_branches.split()]:
                    new_branch_name = f"{
                        project_name}-{datetime.now().strftime('%Y%m%d%H%M%S.%f')}"
                return_text = subprocess.run(
                    ['git', 'checkout', '-b', new_branch_name], capture_output=True, text=True).stdout.strip()
                logger.debug(f"creating new branch {new_branch_name} "
                             f"returned {return_text}")
        except Exception as e:
            logger.fatal(f"Error setting up branch for {project_name}. "
                         "Can't continue.")
            exit(1)

        if not os.path.exists(project_dir):
            os.makedirs(project_dir, exist_ok=True)
            copy_directory(os.path.join(current_parent_dir, "issue_board"), os.path.join(project_dir, "issue_board"))
            logger.info(f"New project dir <{project_dir}> is created.")
            overwrite = True
        os.chdir(project_dir)
        if os.path.exists("pyproject.toml"):
            import tomllib
            with open("pyproject.toml", "r") as f:
                project_toml = tomllib.loads(f.read())

            try:
                toml_project_name = project_toml["project"]["name"]
            except KeyError:
                toml_project_name = None
            if toml_project_name == project_name.replace("_", "-"):
                logger.warning(
                    f"Project <{project_name}> has already been previously initialized.")
            else:
                logger.error("Directory %s already contain a project that is called %s, "
                             "can't initialize it as %s",
                             project_dir, toml_project_name, project_name)
                sys.exit(1)
        else:
            #src_item = os.path.join(os.path.dirname(current_parent_dir), "pyproject.toml")
            #dst_item = os.path.join("pyproject.toml")
            #shutil.copy2(src_item, dst_item)
            uv_init_result = subprocess.run(
                ['uv', 'init', '--name', project_name, '--app'], capture_output=True, text=True)
            uv_init_result.check_returncode()
            overwrite = True
            logger.info(f"New project <{project_name}> is initialized.")

        # make sure the project is initialized with poetry installed packages:
        uv_installed_packages = subprocess.run(
            ['uv', 'tree', '-d', '1', '--package', 'sweteam'], capture_output=True, text=True)
        uv_installed_root_packages = [p for p in uv_installed_packages.stdout.split("\n")
                                      if (p.startswith("├─") or p.startswith("└"))]
        for root_package in uv_installed_root_packages:
            if root_package[3:4] == ["(group:"]:
                uv_add_result = subprocess.run(
                    ['uv', 'add', "=^".join(root_package.split()[1:3]), f"--group={root_package[4].rstrip(')')}"], capture_output=True, text=True)
            else:
                uv_add_result = subprocess.run(
                    ['uv', 'add', ">=".join(root_package.split()[1:3])], capture_output=True, text=True)
            uv_add_result.check_returncode()

        if overwrite:
            logger.debug(f"overwrite flag set to {
                overwrite}, copying bootstrap to {project_team_dir}")
            init_agent_files = utils.initialize_project.initialize_agent_files()
            logger.debug(f"Initializing agent files returned "
                         f"{init_agent_files}")
            copy_directory(current_dir, project_team_dir)
            init_package_result = utils.initialize_project.initialize_package(
                os.path.join(project_dir, os.path.basename(project_dir)))
            logger.debug(f"Initializing package returned "
                         f"{init_package_result}")
            init_Dockerfile_result = utils.initialize_project.initialize_Dockerfile(
                project_name)
            logger.debug(f"Initializing docker returned "
                         f"{init_Dockerfile_result}")
            init_script_result = utils.initialize_project.initialize_startup_script()
            logger.debug(f"Initializing startup script returned "
                         f"{init_script_result}")
            os.makedirs(os.path.dirname(
                config.DIR_STRUCTURE_YAML), exist_ok=True)
            with open(config.DIR_STRUCTURE_YAML, "w") as dddf:
                dddf.write(utils.dir_structure("."))
            logger.info(f"... project <{project_name}> is initialized "
                        "with bootstrap code.")
    except Exception as e:
        logger.fatal("Error %s setting up project: %s",
                     e, project_name, exc_info=e)
        sys.exit(101)

    try:
        os.chdir(project_dir)
        # import importlib
        # sys.path.insert(0, project_dir)
        # actual_project_team = importlib.import_module(project_name+"."+EMBEDDED_DEV_TEAM_NAME)
        # actual_project_team.load_agents()
        uv_result = subprocess.run(
            ['uv', 'sync'], capture_output=True, text=True)
        uv_result.check_returncode()
        logger.info(f"Project <{project_name}> is initialized with "
                    f"bootstrap code. Transferring execution to project"
                    f" <{project_name}>")
        uv_result = subprocess.run(
            ['uv', 'run', '-m', EMBEDDED_DEV_TEAM_NAME, "-p", project_name, "-C", project_dir], check=True)
    except Exception as e:
        logger.error(f"{project_name} agents run into errors "
                     f"{e}. stack: {str(e)}")
        if new_branch_name:
            response = input(f"{project_name} agents run into errors, do "
                             f"you want to drop the new git branch "
                             f"{new_branch_name}?")
            if response.lower() in ["y", "yes"]:
                subprocess.run(['git', 'reset', '--hard'],
                               capture_output=True, text=True)
                subprocess.run(
                    ['git', 'checkout', old_branch_name], capture_output=True, text=True)
                subprocess.run(
                    ['git', 'branch', '-D', new_branch_name], capture_output=True, text=True)


def check_project_branch(project_name, new_branch_name: str = "", protected_branches: list = ['main', 'master']) -> None:
    # if invoke the project.team instead of the bootstrap
    current_file = os.path.realpath(__file__)
    current_dir = os.path.dirname(current_file)
    current_parent_dir = os.path.dirname(current_dir)
    project_dir = current_parent_dir

    try:
        os.chdir(project_dir)
        if new_branch_name and new_branch_name not in protected_branches:
            current_git_branch = subprocess.run(['git', 'checkout', '-b', new_branch_name],
                                                capture_output=True, text=True)
            logger.debug("Created new branch %s and switching to it", new_branch_name)
        else:
            current_git_branch = subprocess.run(
                ['git', 'branch', '--show-current'], capture_output=True, text=True)
            logger.debug("new_branch_name was given as '%s', continue with current branch '%s",
                         new_branch_name, current_git_branch)

        if (current_git_branch in protected_branches):
            logger.fatal(f"??Currently on branch <{current_git_branch}>, "
                         "we shall never change it without a PR.\n"
                         "Please create a new branch or switch to one of the following branches...")
            all_branches = subprocess.run(
                ['git', 'branch', '--list'], capture_output=True, text=True)
            for branch in sorted(all_branches, reverse=True):
                print(f"- {branch}")
                exit(1)

    except FileNotFoundError as e:
        logger.fatal(
            "It seems git was not installed on this system. Can't continue without git.", exc_info=e)
        exit(2)

    except Exception as e:
        logger.fatal("Error setting up git env to change code, can't continue.", exc_info=e)
        exit(1)

    logger.debug(
        f"Invoked as {__package__}. ready to load agents...")


def copy_directory(src_dir, dst_dir):
    """
    Copy a directory and its contents to a new location.

    Args:
        src_dir (str): The path of the source directory to be copied.
        dst_dir (str): The path of the destination directory where the source directory and its contents will be copied to.

    Returns:
        None

    Raises:
        None
    """
    os.makedirs(dst_dir, exist_ok=True)
    for item in os.listdir(src_dir):
        src_item = os.path.join(src_dir, item)
        dst_item = os.path.join(dst_dir, item)
        if os.path.isdir(src_item):
            copy_directory(src_item, dst_item)
        else:
            shutil.copy2(src_item, dst_item)


if __name__ == "__main__":
    match __package__ or '':
        case s if s.endswith("bootstrap_"):  # allows in bootstrap debug avoid transfer flow to default_project
            try:
                project_name = config.PROJECT_NAME
                overwrite = False
                for arg in sys.argv:
                    if arg == "-p":
                        project_name = sys.argv[sys.argv.index(arg) + 1]
                    elif arg == "-o":
                        overwrite = True
                create_project(project_name, overwrite)
            except IndexError:
                logger.fatal(f"Error parsing arguments.\nUsage:\npython -m {os.path.basename(
                    os.path.dirname(__file__))} [-p project_name] [-o True|False]\n")
                sys.exit(1)
            except Exception as e:
                logger.fatal(f"Error parsing arguments: {e}")
                sys.exit(1)
        case '' | None:
            logger.fatal(f"__main__ can't run as a script, please execute it as a module using python -m "
                         f"{os.path.basename(os.path.dirname(__file__))}")
            exit(1)
        case _:
            project_name = os.path.basename(os.getcwd())
            overwrite = False

    with logging_context(config.PROJECT_NAME, config.LOG_LEVEL_CONSOLE, config.LOG_LEVEL,
                         log_file=config.PROJECT_NAME + ".log", level=config.LOG_LEVEL) as logger:
        main()
