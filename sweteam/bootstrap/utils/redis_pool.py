import redis
import redis.asyncio
from typing import Optional, Union, Self, AsyncGenerator
from contextlib import contextmanager, asynccontextmanager
import threading


class RedisConnectionPool:
    """A singleton Redis connection pool manager with context management support.

    This class manages Redis connection pools and provides both synchronous and 
    asynchronous client connections. It ensures connection pools are properly
    cleaned up when no active clients remain.

    Example:
        # Using the class as a context manager
        >>> with RedisConnectionPool() as pool:
        ...     with pool.get_client(host='localhost') as client:
        ...         client.set('key', 'value')
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

        client = redis.Redis(connection_pool=cls._pools[pool_key])
        cls._active_clients += 1

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

        return client

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
