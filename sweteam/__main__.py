"""Entry point for debugging and executing functions or methods within the package.

This script allows dynamic execution of a specified module and function or class method
based on command-line arguments. It supports both synchronous and asynchronous functions.

Usage:
    python -m issue_evaluator <module> <function_or_class.method> [args...]

Args:
    1st: The module to load (e.g., 'src.config').
    2nd: The function or class.method to execute (e.g., 'ClassName.method').
    The rest: Additional arguments to pass to the function or method.

Behavior:
    - If the specified function is a coroutine, it will be executed in an event loop.
    - If no arguments are provided, the default behavior is to execute the `main` function
      from the `main` module.

Returns:
    The result of the executed function or method, printed to stdout.

Raises:
    AttributeError: If the specified attribute or callable is not found.
"""
import sys
import importlib


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        module_name = args[0]
        module = importlib.import_module(module_name, package=__package__)
        if args[1:]:
            func_path = args[1].split('.')
            current = module
            for index, part in enumerate(func_path):
                if not hasattr(current, part):
                    raise AttributeError(f"Attribute '{part}' not found in {current}")
                attr = getattr(current, part)
                if isinstance(attr, type) and index < len(func_path) - 1:
                    # If attr is a class and we're not at the final part, instantiate it
                    current = attr()
                else:
                    current = attr
            if callable(current):
                import inspect
                if inspect.iscoroutinefunction(current):
                    # If the function is a coroutine, run it in an event loop
                    import asyncio
                    loop = asyncio.get_event_loop()
                    result = loop.run_until_complete(current(*args[2:]))
                    print(result)
                else:
                    print(current(*args[2:]))
            else:
                raise AttributeError(f"{args[1]} is not callable")
    else:
        # Default behavior if no arguments are provided
        from .main import main
        main()
