import asyncio
from typing import Callable, Type, TypeVar, ParamSpec
import functools
import warnings

from ..config import config
import redis
import redis.asyncio
from typing import Any, Callable, ClassVar, Optional, Union, Self, AsyncGenerator
from contextlib import contextmanager, asynccontextmanager
import threading
import inspect
import warnings


class RedisConnectionPool:
    """A singleton Redis connection pool manager with context management support.

    This class manages Redis connection pools and provides both synchronous and 
    asynchronous client connections. It ensures connection pools are properly
    cleaned up when no active clients remain.

    Example:
        # Using the class as a context manager
        >>> import os
        >>> with RedisConnectionPool.get_client(host=os.getenv("REDIS_HOST")) as client:
        ...         client.set('key', 'value')
        True
    """
    _instance = None
    _lock = threading.Lock()
    _pools = {}
    _async_pools = {}
    _active_clients = 0
    _active_async_clients = 0

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    @classmethod
    def _create_pool_key(cls, **kwargs) -> str:
        """Create a unique key for the pool based on connection parameters"""
        sorted_items = sorted(kwargs.items())
        return ','.join(f"{k}={v}" for k, v in sorted_items)

    @classmethod
    def get_client(cls, **kwargs) -> redis.Redis:
        """Get a Redis client from the connection pool.

        Args:
            **kwargs: Redis connection parameters (host, port, db, etc.)

        Returns:
            redis.Redis: A Redis client instance that can be used as a context manager
        """
        pool_key = cls._create_pool_key(**kwargs)

        if pool_key not in cls._pools:
            cls._pools[pool_key] = redis.ConnectionPool(**kwargs)
            cls._pools[pool_key].disconnect()

        client = redis.Redis(connection_pool=cls._pools[pool_key])
        cls._active_clients += 1

        try:
            try:
                client.ping()
            except redis.exceptions.ConnectionError:
                pass
        except redis.RedisError as e:
            warnings.warn(f"Redis error: {e}", UserWarning)
            raise
        except asyncio.CancelledError as e:
            # likely previous connection was not closed properly and was in a cancelled state
            client.close()
            client.connection_pool.disconnect()
            cls._pools[pool_key] = redis.ConnectionPool(**kwargs)
            client = redis.Redis(connection_pool=cls._pools[pool_key])
        except Exception as e:
            warnings.warn(f"Unexpected error pinging redis client: {e}", UserWarning)
            raise
        return client

    @classmethod
    def get_async_client(cls, **kwargs) -> redis.asyncio.Redis:
        """Get an async Redis client from the connection pool.

        Args:
            **kwargs: Redis connection parameters (host, port, db, etc.)

        Returns:
            redis.asyncio.Redis: An async Redis client instance that can be used as a context manager
        """
        pool_key = cls._create_pool_key(**kwargs)

        if pool_key not in cls._async_pools:
            cls._async_pools[pool_key] = redis.asyncio.ConnectionPool(**kwargs)

        client = redis.asyncio.Redis(connection_pool=cls._async_pools[pool_key])
        cls._active_async_clients += 1

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, schedule ping check without blocking
                async def check_ping():
                    try:
                        await asyncio.wait_for(client.ping(), timeout=1.0)
                    except Exception as e:
                        await client.close()
                        warnings.warn(f"Redis ping failed, scheduled check: {e}", UserWarning)
                loop.create_task(check_ping())
            else:
                loop.run_until_complete(asyncio.wait_for(client.ping(), timeout=1.0))
        except redis.RedisError as e:
            warnings.warn(f"Redis Async error: {e}", UserWarning)
            raise
        except asyncio.CancelledError as e:
            client.close()
            client.connection_pool.disconnect()
            cls._async_pools[pool_key] = redis.asyncio.ConnectionPool(**kwargs)
            client = redis.asyncio.Redis(connection_pool=cls._async_pools[pool_key])
        except Exception as e:
            warnings.warn(f"Unexpected error pinging async redis client: {e}", UserWarning)
            raise
        return client

    def __init__(self):
        """Initialize the RedisConnectionPool instance."""

        if self._instance is not None:
            raise RuntimeError("This class is a singleton. Use get_client() to access it.")

    def __enter__(self) -> Self:
        """Enter the context manager.

        Returns:
            Self: The RedisConnectionPool instance
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager and cleanup resources."""
        # Cleanup sync pools
        for pool in self._pools.values():
            pool.disconnect()
        self._pools.clear()
        self._active_clients = 0

        # Cleanup async pools
        for pool in self._async_pools.values():
            try:
                import asyncio
                asyncio.run(pool.disconnect())
            except Exception:
                pass
        self._async_pools.clear()
        self._active_async_clients = 0

    async def __aenter__(self) -> Self:
        """Enter the async context manager.

        Returns:
            Self: The RedisConnectionPool instance
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager and cleanup resources."""
        # Cleanup sync pools
        for pool in self._pools.values():
            pool.disconnect()
        self._pools.clear()
        self._active_clients = 0

        # Cleanup async pools
        for pool in self._async_pools.values():
            await pool.disconnect()
        self._async_pools.clear()

    @classmethod
    def shutdown(cls):
        """Force shutdown all connection pools."""
        for pool in cls._pools.values():
            pool.disconnect()
        cls._pools.clear()

        for pool in cls._async_pools.values():
            try:
                import asyncio
                asyncio.run(pool.disconnect())
            except Exception:
                pass
        cls._async_pools.clear()


class NotFoundInCache(Exception):
    """Raised when a key is not found in the cache."""
    pass


class RedisCache:
    """A Redis cache wrapper that provides namespaced key-value operations.

    Example:
        >>> import os
        >>> cache = RedisCache(host=os.getenv("REDIS_HOST"), port=6379)
        >>> cache.set('test_key', 'test_value')
        >>> cache.get('test_key')
        b'test_value'
        >>> cache.set_json('json_key', '$', {'name': 'test'})
        True
        >>> cache.get_json('json_key', '$.name')
        ['test']
        >>> cache.get_json('json_key', '.')
        {'name': 'test'}
    """

    def __init__(self, host: str = None, port: int = None,
                 username: str = None, password: str = None,
                 namespace: str = None):
        self.host = host or config.REDIS_HOST
        self.port = port or config.REDIS_PORT
        self.username = username or config.REDIS_USERNAME
        self.password = password or config.REDIS_PASSWORD
        self.namespace = namespace or config.PROJECT_NAME

        self.redis_client = RedisConnectionPool.get_client(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password
        )

    def get(self, key: str):
        namespaced_key = f"{self.namespace}:{key}"
        value = self.redis_client.get(namespaced_key)
        if value is None:
            raise NotFoundInCache(f"Key '{namespaced_key}' not found in cache.")
        return value

    def set(self, key: str, value):
        namespaced_key = f"{self.namespace}:{key}"
        self.redis_client.set(namespaced_key, value)

    @staticmethod
    def _get_nested_value(data: dict, dot_path: str):
        parts = dot_path.split('.')
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                raise KeyError(f"Path '{dot_path}' not found.")
        return current

    @staticmethod
    def _set_nested_value(data: dict, dot_path: str, value):
        parts = dot_path.split('.')
        current = data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        return data

    def get_json(self, key: str, field: str = "."):
        """
        Retrieves a nested property from the JSON object stored at "{namespace}:{key}".
        Raises NotFoundInCache if the JSON object does not exist.
        Raises ValueError if the nested field is not found.
        """
        namespaced_key = f"{self.namespace}:{key}"
        try:
            data = self.redis_client.json().get(namespaced_key, field)
            if data is None:
                data = self.redis_client.json().get(namespaced_key, '.')
                if data is None:
                    raise KeyError(f"JSON object at key '{namespaced_key}' not found in cache.")
                else:
                    raise ValueError(f"Field '{field}' not found in JSON object for key '{namespaced_key}'.")
            else:
                return data
        except Exception as e:
            raise NotFoundInCache(f"Error retrieving '{namespaced_key}' due to {e}.")

    def set_json(self, key: str, field: str, value):
        """
        Updates the JSON object stored at "{namespace}:{key}" by setting the given
        nested field (using dot notation) to value. If the JSON object does not exist,
        it is created.
        """
        namespaced_key = f"{self.namespace}:{key}"
        data = self.redis_client.json().get(namespaced_key, '.')
        if data is None:
            data = {}
            updated_data = self._set_nested_value(data, field.lstrip("$."), value)
            return self.redis_client.json().set(namespaced_key, '.', updated_data)
        else:
            return self.redis_client.json().set(namespaced_key, field, value)


T = TypeVar('T')
P = ParamSpec('P')


def with_redis_cache(return_type: Type[T]) -> Callable[[Callable[P, Any]], Callable[P, Any]]:
    """Decorator factory to cache the result of function calls in Redis. Works with both sync and async functions.

    Example:
        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class User:
        ...     name: str
        ...     def to_dict(self):
        ...         return {'name': self.name}
        ...
        >>> @with_redis_cache(User)
        ... def get_user(name: str) -> User:
        ...     return User(name=name)
        ...
        >>> # First call - caches result
        >>> user1 = get_user('test')
        >>> user1.name
        'test'
        >>> # Second call - returns from cache
        >>> user2 = get_user('test')
        >>> user2.name
        'test'
        >>> # Clear cache by setting use_cache=False
        >>> user3 = get_user('test', use_cache=False)
        >>> user3.name
        'test'
    """
    def decorator(func: Callable[P, Any]) -> Callable[P, Any]:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                use_cache = kwargs.pop("use_cache", True)
                cache = RedisCache()
                key = f"{func.__name__}:{args}:{kwargs}"
                if use_cache:
                    try:
                        cached_value = cache.get_json(key, ".")
                        if cached_value is None:
                            raise KeyError
                        if isinstance(cached_value, return_type):
                            return cached_value
                        return return_type(**cached_value)
                    except Exception:
                        warnings.warn(f"Cache miss for key '{key}'. Computing async value...", UserWarning)
                result = await func(*args, **kwargs)
                try:
                    for method in ["to_dict", "model_dump", "dict"]:
                        if hasattr(result, method):
                            result_to_cache = getattr(result, method)()
                            break
                    else:
                        result_to_cache = result
                    cache.set_json(key, "$", result_to_cache)
                except Exception as e:
                    warnings.warn(f"Error setting key '{key}' in cache.", UserWarning, exc_info=e)
                return result
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                use_cache = kwargs.pop("use_cache", True)
                cache = RedisCache()
                key = f"{func.__name__}:{args}:{kwargs}"
                if use_cache:
                    try:
                        cached_value = cache.get_json(key, ".")
                        if cached_value is None:
                            raise KeyError
                        if isinstance(cached_value, return_type):
                            return cached_value
                        return return_type(**cached_value)
                    except Exception:
                        warnings.warn(f"Cache miss for key '{key}'. Computing value...", UserWarning)
                result = func(*args, **kwargs)
                try:
                    for method in ["to_dict", "model_dump", "dict"]:
                        if hasattr(result, method):
                            result_to_cache = getattr(result, method)()
                            break
                    else:
                        result_to_cache = result
                    cache.set_json(key, "$", result_to_cache)
                except Exception as e:
                    warnings.warn(f"Error setting key '{key}' in cache.", UserWarning, exc_info=e)
                return result
            return sync_wrapper
    return decorator
