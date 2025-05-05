"""code setting up logger using context manager"""

import logging
import logging.handlers
from contextlib import contextmanager
from typing import Generator
import os
from ..config import config


def get_logger(name: str, stream: str | bool = 'INFO', file: str | bool = '',
               *, log_file: str = '', level: str = 'DEBUG',
               redis_level: str | bool = '') -> logging.Logger:
    """configure a logger with multiple handlers

    Args:
        name: the name of the logger that will be shown in the logs
        stream: set stream log level, default is 'INFO'
        file: set rotating file log level, default is OFF
        level: the logger's own level, default is 'DEBUG'
        redis_level: set redis log level, default is OFF

    Returns:
        logger: the logger object with name and handlers set up
    """
    LOG_LEVEL = {
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "CRITICAL": logging.CRITICAL
    }
    logger_ = logging.getLogger(name)
    logger_.setLevel(LOG_LEVEL[level] if level in LOG_LEVEL else logging.DEBUG)

    console_handler = logging.StreamHandler()
    if stream in LOG_LEVEL and (console_handler.__class__ not in
                                {h.__class__ for h in logger_.handlers}):
        console_handler.setLevel(LOG_LEVEL[stream])
        c_format = logging.Formatter("#%(levelname)9s - %(name)s - %(filename)s:%(lineno)d"
                                     " %(funcName)s() - %(message)s")
        console_handler.setFormatter(c_format)
        logger_.addHandler(console_handler)

    log_file = log_file or f"{__file__[:-3]}.log"
    file_handler_class = logging.handlers.RotatingFileHandler
    if file in LOG_LEVEL:
        if (file_handler_class in {h.__class__ for h in logger_.handlers}):
            logger_.warning("Setting logging-to-file to level %s but Logger %s already has a file handler,"
                            " skipping...", file, name)
        else:
            file_handler = file_handler_class(
                log_file, maxBytes=10485760, backupCount=9, encoding='utf-8')
            file_handler.setLevel(LOG_LEVEL[file])
            f_format = logging.Formatter("%(asctime)s %(levelname)s - %(name)s "
                                         "- %(filename)s:%(lineno)d  "
                                         "%(module)s.%(funcName)s() - %(message)s")
            file_handler.setFormatter(f_format)
            logger_.addHandler(file_handler)

    # Add Redis handler if configured
    if redis_level in LOG_LEVEL:
        from .redis_log_handler import RedisLogHandler
        redis_handler = RedisLogHandler(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            stream_name=f"{config.PROJECT_NAME}_logs"
        )
        redis_handler.setLevel(LOG_LEVEL[redis_level])
        r_format = logging.Formatter("%(message)s")
        redis_handler.setFormatter(r_format)
        logger_.addHandler(redis_handler)

    if not logger_.hasHandlers():
        logger_.addHandler(logging.NullHandler())

    return logger_


def get_default_logger(name: str = '', stream: str | bool | None = None, file: str | bool | None = None,
                       *, log_file: str | None = None, level: str | None = None, redis_level: str | None = None) -> logging.Logger:
    logger_name = config.PROJECT_NAME if name is None else name
    stream_level = config.LOG_LEVEL_CONSOLE if stream is None else stream
    file_level = config.LOG_LEVEL if file is None else file
    log_level = config.LOG_LEVEL if level is None else level
    redis_level = config.LOG_LEVEL_REDIS if redis_level is None else redis_level
    log_filename = ((config.PROJECT_NAME or os.path.basename(
        os.getcwd())) + ".log") if log_file is None else log_file

    return get_logger(logger_name, stream_level, file_level, log_file=log_filename, level=log_level, redis_level=redis_level)


logger = get_default_logger((__package__ or __name__ or "default_logger"))
logger.debug(
    "utils default logger initialized with the following handlers %s.", logger.handlers)


@contextmanager
def logging_context(*args, **kwargs) -> Generator[logging.Logger, None, None]:
    """use contextmanager to setup/shutdown logging
    Only use in the main function of a project, not a sub module
    """
    try:
        yield logger
    finally:
        try:
            if isinstance(logger, logging.Logger):
                logger.info("shutting down the logging facility...")
        except Exception as e:
            print(f"Can't log final message to logger, {e=}"
                  "shutting down the logging facility...")
        logging.shutdown()
