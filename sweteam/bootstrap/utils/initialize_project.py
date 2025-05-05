import os
from .log import logger


def initialize_agent_files(agent_parent_dir: str | None = None) -> str:
    """Initialize the agent files
    """
    logger.debug(
        f"<Initializing> - updating agents instructions as part of project setup. Should not be used in production")
    import os
    import json
    from ..defs.agent_defs import agents, tool_instructions, standard_tools

    agents_dir = os.path.join(
        agent_parent_dir if agent_parent_dir else os.path.dirname(os.path.dirname(__file__)), "agents")
    logger.info(f"updating agent info in {agents_dir=}")
    agent_json_files = [entry for entry in os.listdir(agents_dir) if entry.endswith(".json")]
    for agent_json in agent_json_files:
        fullpath_json = os.path.join(agents_dir, agent_json)
        agent_name = agent_json.removesuffix(".json")
        if agents.get(agent_name):
            agent: dict = agents.get(agent_name)
            with open(fullpath_json, "r") as f:
                config_in_json: dict = json.load(f)

            config_in_json.update(agent)

            for idx, tool in enumerate(agent.get("tools", [])):
                if isinstance(tool, str):
                    index = config_in_json["tools"].index(tool)
                    config_in_json["tools"][index:index +
                                            1] = [t for t in standard_tools if t.get("function", {"name": ""}).get("name") == tool]
                    config_in_json["instruction"] = config_in_json.get("instruction", '') \
                        + tool_instructions.get(tool, '')

            with open(fullpath_json, "w") as f:
                json.dump(config_in_json, f, indent=4)
    logger.info(
        f"<Initializing> - updated {len(agent_json_files)} agents instructions")
    return 'done.'


def initialize_startup_script(project_dir: str | None = None) -> str:
    """Initialize the startup shell script
    """
    if project_dir is None:
        project_dir = os.getcwd()
    project_name = os.path.basename(project_dir)
    script_path = os.path.join(project_dir, "run.sh")
    base_script = f"""\
#!/bin/bash

# Function to display usage
usage() {{
    echo "Usage: $0 [-t test_name] [-k]"
    exit 1
}}

# Parse command line options
while getopts ":t:k" opt; do
  case $opt in
    t )
      test_name=$OPTARG
      ;;
    k )
      kill_docker=true
      ;;
    * )
      usage
      ;;
  esac
done

# Check if both -t and -k are provided
if [[ ! -z "$test_name" && ! -z "$kill_docker" ]]; then
    echo "Error: -t and -k options cannot be used together."
    usage
fi

# Execute the appropriate command based on the options
if [ ! -z "$test_name" ]; then
    echo "(re)starting docker compose"
    docker-compose up -d
    echo "Running python -m $test_name"
    python -m "$test_name"
elif [ ! -z "$kill_docker" ]; then
    echo "Running docker-compose down"
    docker-compose down
else
    docker-compose up -d
    docker-compose logs
fi
"""
    if os.path.exists(script_path):
        return (f"<init startup script> {script_path} already exist, will not overwrite it, exiting...")
    else:
        try:
            with open(script_path, "w") as df:
                df.write(base_script)
            current_permissions = os.stat(script_path).st_mode
            os.chmod(script_path, current_permissions | 0o111)
        except Exception as e:
            return f"<init startup script> got an Error: {e}"
        else:
            return f"<init startup script> {script_path} for {project_name} has been successfully initialized."


def initialize_Dockerfile(project_name: str | None = None, dockerfile_path: str | None = None) -> str:
    """Initialize the Dockerfile in the given directory
    """
    base_Dockerfile = f"""\
# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy pyproject.toml and poetry.lock files to the container
COPY pyproject.toml poetry.lock ./

# Install the project dependencies
RUN poetry install --no-root

# Copy the rest of the application code to the container
COPY . .

# Specify the command to run your application
CMD ["poetry", "run", "python", "-m", "{project_name}"]
"""
    if project_name is None:
        project_name = os.path.basename((os.getcwd()))
    if dockerfile_path is None:
        dockerfile_path = os.path.join(os.getcwd(), "Dockerfile")
    base_Dockerfile.replace("{project_name}", project_name)
    if os.path.exists(dockerfile_path):
        result = (f"<init Dockerfile> {dockerfile_path} already exist, will not overwrite it, exiting...\n")
    else:
        try:
            with open(dockerfile_path, "w") as df:
                df.write(base_Dockerfile)
        except Exception as e:
            result = f"<init Dockerfile> got an Error: {e}\n"
        else:
            result = f"<init Dockerfile> {dockerfile_path} for {project_name} has been successfully initialized.\n"
    base_docker_compose = f"""\
services:
  {project_name}:
    build: .
    command: poetry run python -m {project_name}
    ports:
      - "${{SERVER_PORT:-8080}}:8080"
    restart: always
"""
    docker_compose_path = os.path.join(os.path.dirname(
        (dockerfile_path)), "docker-compose.yaml")
    if os.path.exists(docker_compose_path):
        result += (f"<init Dockerfile> {docker_compose_path} already exist, will not overwrite it, exiting...")
    else:
        try:
            with open(docker_compose_path, "w") as df:
                df.write(base_docker_compose)
        except Exception as e:
            result += f"<init Dockerfile> got an Error: {e}"
        else:
            result += (f"<init Dockerfile> {docker_compose_path} for "
                       "{project_name} has been successfully initialized.")
    return result


def initialize_package(package_dir: str | None = None) -> str:
    """Initialize the __init__.py and __manin__.py files of a package.

    Args:
      package_dir: the path to the package, default is the namesake of the project

    Returns:
      the status of the package initializatio
    """
    if package_dir is None:
        # the default package dir is a namesake of the project under the project_dir
        package_dir = os.path.join(os.getcwd(), os.path.basename(os.getcwd()))
    base_main = '''\
"""Project base package.

Example::
    >>> print("Hello World!")
    Hello World!
"""
def test() -> str:
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    test()
'''
    try:
        main_file_path = os.path.join(package_dir, "__main__.py")
        with open(main_file_path, "w") as mf:
            mf.write(base_main)
    except Exception as e:
        return f"<Init package> received Error: {e}"
    else:
        return f"<Init package> successful."
