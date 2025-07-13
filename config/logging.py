import sys
import os
from typing import Dict, Any
from loguru import logger

from .settings import get_settings


def setup_logging():
    """
    Configure logging for the application using Loguru.
    """
    settings = get_settings()
    
    # Remove default logger
    logger.remove()
    
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(settings.log_file_path)
    os.makedirs(log_dir, exist_ok=True)
    
    # Console logging configuration
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    # File logging configuration
    if settings.log_format == "json":
        file_format = (
            "{{\"time\": \"{time:YYYY-MM-DD HH:mm:ss}\", "
            "\"level\": \"{level}\", "
            "\"module\": \"{name}\", "
            "\"function\": \"{function}\", "
            "\"line\": {line}, "
            "\"message\": \"{message}\"}}"
        )
    else:
        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"
        )
    
    # Add console handler
    logger.add(
        sys.stderr,
        format=console_format,
        level=settings.log_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
        enqueue=True
    )
    
    # Add file handler
    logger.add(
        settings.log_file_path,
        format=file_format,
        level=settings.log_level,
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        compression="gz",
        backtrace=True,
        diagnose=True,
        enqueue=True
    )
    
    # Add error file handler
    error_log_path = settings.log_file_path.replace(".log", "_errors.log")
    logger.add(
        error_log_path,
        format=file_format,
        level="ERROR",
        rotation="1 day",
        retention="90 days",
        compression="gz",
        backtrace=True,
        diagnose=True,
        enqueue=True
    )
    
    # Configure specific loggers
    configure_third_party_loggers(settings)
    
    logger.info(f"Logging configured for {settings.app_name} v{settings.app_version}")
    logger.info(f"Log level: {settings.log_level}")
    logger.info(f"Log file: {settings.log_file_path}")


def configure_third_party_loggers(settings):
    """Configure third-party library loggers."""
    import logging
    
    # Suppress noisy loggers in production
    if settings.is_production:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("neo4j").setLevel(logging.WARNING)
        logging.getLogger("graphiti").setLevel(logging.INFO)
    
    # Configure notion-client logger
    logging.getLogger("notion_client").setLevel(logging.INFO)
    
    # Configure asyncio logger
    logging.getLogger("asyncio").setLevel(logging.INFO)


def get_logger(name: str):
    """
    Get a logger instance with the given name.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Logger instance
    """
    return logger.bind(name=name)


def log_function_call(func_name: str, **kwargs):
    """
    Log a function call with its parameters.
    
    Args:
        func_name: Name of the function being called
        **kwargs: Function parameters to log
    """
    logger.debug(f"Calling {func_name} with params: {kwargs}")


def log_performance(func_name: str, duration: float, **kwargs):
    """
    Log performance metrics for a function.
    
    Args:
        func_name: Name of the function
        duration: Execution duration in seconds
        **kwargs: Additional metrics to log
    """
    logger.info(f"Performance: {func_name} took {duration:.3f}s", **kwargs)


def log_error(error: Exception, context: Dict[str, Any] = None):
    """
    Log an error with context information.
    
    Args:
        error: Exception that occurred
        context: Additional context information
    """
    context = context or {}
    logger.error(f"Error: {type(error).__name__}: {str(error)}", **context)


def log_sync_operation(operation: str, **kwargs):
    """
    Log sync operation details.
    
    Args:
        operation: Type of sync operation
        **kwargs: Operation details
    """
    logger.info(f"Sync operation: {operation}", **kwargs)


def log_mcp_request(tool_name: str, parameters: Dict[str, Any]):
    """
    Log MCP tool request.
    
    Args:
        tool_name: Name of the MCP tool
        parameters: Tool parameters
    """
    logger.info(f"MCP Request: {tool_name}", parameters=parameters)


def log_mcp_response(tool_name: str, success: bool, duration: float, result_count: int = None):
    """
    Log MCP tool response.
    
    Args:
        tool_name: Name of the MCP tool
        success: Whether the operation was successful
        duration: Response time in seconds
        result_count: Number of results returned (if applicable)
    """
    extra = {
        "success": success,
        "duration": duration,
        "result_count": result_count
    }
    logger.info(f"MCP Response: {tool_name}", **extra)


class LoggingMixin:
    """
    Mixin class that provides logging capabilities to other classes.
    """
    
    @property
    def logger(self):
        """Get logger instance for this class."""
        return logger.bind(name=self.__class__.__name__)
    
    def log_debug(self, message: str, **kwargs):
        """Log debug message."""
        self.logger.debug(message, **kwargs)
    
    def log_info(self, message: str, **kwargs):
        """Log info message."""
        self.logger.info(message, **kwargs)
    
    def log_warning(self, message: str, **kwargs):
        """Log warning message."""
        self.logger.warning(message, **kwargs)
    
    def log_error(self, message: str, **kwargs):
        """Log error message."""
        self.logger.error(message, **kwargs)
    
    def log_exception(self, message: str, **kwargs):
        """Log exception with traceback."""
        self.logger.exception(message, **kwargs)


# Context manager for logging function execution
class LogExecutionTime:
    """
    Context manager to log execution time of code blocks.
    """
    
    def __init__(self, name: str, logger_instance=None):
        self.name = name
        self.logger = logger_instance or logger
        self.start_time = None
    
    def __enter__(self):
        import time
        self.start_time = time.time()
        self.logger.debug(f"Starting {self.name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        duration = time.time() - self.start_time
        
        if exc_type is None:
            self.logger.debug(f"Completed {self.name} in {duration:.3f}s")
        else:
            self.logger.error(f"Failed {self.name} after {duration:.3f}s: {exc_val}")
        
        return False  # Don't suppress exceptions