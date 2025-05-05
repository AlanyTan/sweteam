# Utils Directory

The `utils` directory contains utility modules that provide supporting functionalities for the Issue Management Assistant. These utilities are designed to simplify common tasks, enhance modularity, and improve code maintainability.

## Modules Overview

### 1. `log.py`
**Purpose**: Provides logging utilities for the application.

- **Key Functions**:
  - `get_logger(name: str, stream: str | bool = 'INFO', file: str | bool = '', ...) -> logging.Logger`: Configures and returns a logger instance with optional file and Redis logging support.
  - `get_default_logger()`: Returns a default logger instance based on the configuration.

- **Usage**:
  ```python
  from utils.log import get_logger

  logger = get_logger("my_logger")
  logger.info("This is an info message.")
  ```

### 2. `file_utils.py`
**Purpose**: Provides utilities for file and directory operations.

- **Key Functions**:
  - `dir_tree(path_: str, return_yaml: bool = False) -> str`: Generates a tree structure of a directory in YAML or plain text format.
  - `dir_structure(path: str | dict = {}, action: str = 'read', ...) -> str`: Manages directory structures, supporting actions like `read` and `update`.
  - `dir_contains(directory, files: bool = True, dirs: bool = False, ...)`: Checks if a directory contains specific files or subdirectories matching a pattern.

- **Usage**:
  ```python
  from utils.file_utils import dir_tree, dir_structure

  tree = dir_tree("/path/to/dir", return_yaml=True)
  print(tree)

  structure = dir_structure(path="/path/to/dir", action="read")
  print(structure)
  ```

### 3. `decorators.py`
**Purpose**: Provides reusable decorators for timing and logging function execution.

- **Key Functions**:
  - `timed_execution(f: Callable) -> Callable`: Logs the execution time of a function.
  - `timed_async_execution(f: Callable) -> Callable`: Logs the execution time of an asynchronous function.

- **Usage**:
  ```python
  from utils.decorators import timed_execution

  @timed_execution
  def my_function():
      pass
  ```

### 4. `__main__.py`
**Purpose**: Entry point for running utilities directly from the command line.

- **Key Features**:
  - Supports commands like `update_agents`, `issue_manager`, and `dir_structure`.

- **Usage**:
  ```bash
  python -m utils dir_structure path=/path/to/dir action=read
  ```

### 5. `__init__.py`
**Purpose**: Initializes the `utils` package and provides helper functions.

- **Key Functions**:
  - `get_dot_notation_value(dict_obj: dict, dot_path: str, default=None)`: Accesses nested dictionary values using dot notation.
  - `execute_module(module_name: str, method_name: str | None = None, ...) -> str`: Dynamically executes a module or method.

- **Usage**:
  ```python
  from utils import get_dot_notation_value

  value = get_dot_notation_value(my_dict, "key.subkey")
  ```