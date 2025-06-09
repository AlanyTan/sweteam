from typing import Callable, Any, TypeVar, ParamSpec, ContextManager, Coroutine
from functools import wraps
from contextlib import contextmanager
import time
from .log import logger

T = TypeVar('T')
P = ParamSpec('P')

_timing_context_depth = 0


def _get_method_name(f: Callable) -> str:
    return f.__self__.__class__.__name__ + "." + f.__name__ if hasattr(f, '__self__') else f.__name__


@contextmanager
def timing_context(name: str = "", is_async: bool = False):
    """Context manager for timing code execution.

    Args:
        name (str, optional): Name of the operation being timed. Defaults to None.
        is_async (bool, optional): Whether this is an async operation. Defaults to False.

    Example:
        with timing_context("my_operation"):
            # code to time
            result = do_something()
    """
    global _timing_context_depth
    _timing_context_depth += 1
    depth = _timing_context_depth
    prefix = "Async " if is_async else ""
    operation_name = str(name or "operation")
    logger.info("%s Start timed %sexecution of %s ...", "." * depth, prefix, operation_name)
    start_time = time.time()
    try:
        yield None
    finally:
        elapsed_time = time.time() - start_time
        logger.info("%s Timed %sExecution of %s completed in %.2f seconds.",
                    "_" * depth, prefix, operation_name, elapsed_time)
        _timing_context_depth -= 1


def timed_execution(f: Callable[P, T]) -> Callable[P, T]:
    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        method_name = _get_method_name(f)
        with timing_context(method_name):
            return f(*args, **kwargs)
    return wrapper


def timed_async_execution(f: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, Coroutine[Any, Any, T]]:
    @wraps(f)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        method_name = _get_method_name(f)
        with timing_context(method_name, is_async=True):
            return await f(*args, **kwargs)
    return wrapper
