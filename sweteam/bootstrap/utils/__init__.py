"""
This module contains utility functions for working with files.

Usage:
    python -m utils [update_agent]
"""

import re
from .file_utils import dir_structure
from typing import Callable, Any
import subprocess
from datetime import datetime
from .initialize_project import initialize_package, initialize_Dockerfile, initialize_startup_script
from .log import logger
from ..config import config
from .jira_issue import issue_manager


def get_dot_notation_value(dict_obj: dict, dot_path: str, default=None):
    """
    Access nested dictionary values using dot notation

    Args:
        dict_obj (dict): The dictionary to search
        dot_path (str): Path to value using dot notation (e.g. "status.name")
        default (any): value to return if the key is not found, None if ommited
    Returns:
        The value if found, None if not found
    """
    try:
        parts = dot_path.split('.')
        value = dict_obj
        for part in parts:
            value = value[part]
        return value
    except (KeyError, TypeError):
        return default


def execute_module(module_name: str, method_name: str | None = None, args: list = [], **kwargs) -> str:
    """Execute a specified method from a Python module.

    Args:
        module_name: Name of the module to execute.
        method_name: Name of the method to execute.
        args: Arguments for the method.
        kwargs: Keyword arguments for the method.

    Returns: 
        A dictionary with 'output' or 'error' as a key.

    Example::
        >>> import os
        >>> execute_module('math', 'sqrt', args=[16]).strip()
        '{"output": 4.0}'
        >>> result = execute_module('os', 'getcwd')
        >>> os.getcwd() in result
        True

    """
    # Prepare the command to execute
    if method_name:
        python_command = f"import json, {module_name};" \
            "output={};" \
            f"output['output'] = getattr({module_name}, '{method_name}')(*{args}, **{kwargs}); " \
            "print(json.dumps(output))"
        python_mode = "-c"
        python_command_args = []
    else:
        python_command = f"{module_name}"
        python_command_args = args
        python_mode = "-m"

    logger.debug(f"execute_module - Executing {python_command}")
    # Execute the command as a subprocess
    try:
        result = subprocess.run(['python', python_mode, python_command, *python_command_args],
                                capture_output=True, text=True, check=False, shell=False, timeout=120)
        if result.returncode == 0:
            logger.debug(
                f"execute_module -Execution returned 0 exit code")
            if method_name:
                return result.stdout
            else:
                return result.stdout.strip()
        else:
            logger.error("execute_module -Execution returned non-0 exit code. Output: %s; Error: %s",
                         result.stdout, result.stderr)
            return f'Execution finished with non-0 return code: {result.stderr}, Output: {result.stdout}'
    except subprocess.CalledProcessError as e:
        logger.error(
            f"<execute_module -Execution failed. Error: {e}")
        return f'Execution failed with error: {e}'
    except subprocess.TimeoutExpired:
        logger.error(
            f"<execute_module -Execution failed. Error: timeout")
        return f'Execution timed out, if this happens often, please check if this module execution is hang.'
    except Exception as e:
        logger.error(
            f"<execute_module -Execution failed. Error: {e}")
        return f'Execution failed with error: {e}'


def execute_command(command_name: str, args: list = [], asynchronous: bool = False) -> str:
    """Execute a specified method from a Python module.

    Args:
        command_name: Name of the module to execute.
        args: Arguments for the method.

    Returns: 
        A dictionary with 'output' or 'error' as a key.

    Example::
        >>> import os
        >>> execute_command('echo', args=['hello', 'world'])
        '{"output": "hello world\\\\n"}'
        >>> result = execute_command('pwd')
        >>> import json
        >>> json.loads(result).get('output').strip() == os.getcwd()
        True
        >>> execute_command('ls', args=['non-exist.dir'])
        "execute_command returned non-0 return code. Output:, Error: ls: cannot access 'non-exist.dir': No such file or directory\\n"
    """
    import json
    # Execute the command as a subprocess
    try:
        if asynchronous:
            process = subprocess.Popen([command_name, *args],
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       text=True,
                                       shell=False)
            logger.debug(
                f"execute_command - started parallel process: {process.pid}")
            return f"started {command_name} in a parallel process: {process.pid}"
        else:
            result = subprocess.run([command_name, *args],
                                    capture_output=True, text=True, check=False, shell=False, timeout=120)
            logger.debug(
                f"execute_command -returned {result.stdout}.")
            output = {'output': result.stdout}
            if result.returncode == 0:
                return json.dumps(output)
            else:
                logger.error(
                    f"execute_command -Execution returned non-0 exit code. Error: {result.stderr}")
                return f"execute_command returned non-0 return code. Output:{result.stdout}, Error: {result.stderr}"
    except subprocess.CalledProcessError as e:
        logger.error(
            f"execute_command -Execution failed. Error: {e}")
        return f"error: {e}"
    except subprocess.TimeoutExpired:
        logger.error(
            f"execute_command -Execution failed. Error: timeout")
        return f'Execution timed out, if this happens often, please check if this module execution is hang.'
    except Exception as e:
        logger.error(
            f"execute_command -Execution failed. Error: {e}")
        return f'Execution failed with error: {e}'
