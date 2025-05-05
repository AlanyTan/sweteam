import logging
import json
import redis
from typing import Optional
from .redis_pool import RedisConnectionPool
from ..config import config


class RedisLogHandler(logging.Handler):
    def __init__(self, host: str = 'localhost', port: int = 6379,
                 stream_name: Optional[str] = None, max_len: int = 10000,
                 redis_client: Optional[redis.Redis] = None):
        super().__init__()
        self.stream_name = stream_name or f"{config.PROJECT_NAME}_logs"
        self.max_len = max_len
        self.redis_client = redis_client or RedisConnectionPool.get_client(host=host, port=port)
        self.notification_channel = f"{self.stream_name}:new"

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            log_entry = {
                'timestamp': record.created,
                'level': record.levelname,
                'logger': record.name,
                'function': record.funcName,
                'message': msg
            }

            # Add to Redis stream with automatic ID generation
            log_id = self.redis_client.xadd(
                self.stream_name,
                log_entry,
                maxlen=self.max_len,
                approximate=True
            )

            # Publish notification about new log entry
            self.redis_client.publish(self.notification_channel, log_id)

        except Exception:
            self.handleError(record)
