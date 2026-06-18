"""Structured logging configuration."""
import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, "query"):
            log_data["query"] = record.query
        if hasattr(record, "sql"):
            log_data["sql"] = record.sql
        if hasattr(record, "execution_time_ms"):
            log_data["execution_time_ms"] = record.execution_time_ms
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "route"):
            log_data["route"] = record.route
        if hasattr(record, "tables"):
            log_data["tables"] = record.tables
        if hasattr(record, "rows_returned"):
            log_data["rows_returned"] = record.rows_returned
        if hasattr(record, "llm_tokens"):
            log_data["llm_tokens"] = record.llm_tokens
        if hasattr(record, "error_type"):
            log_data["error_type"] = record.error_type
        if hasattr(record, "stack_trace"):
            log_data["stack_trace"] = record.stack_trace

        # Add any extra fields from record
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


def setup_logging(level: str = "INFO", format_type: str = "json") -> logging.Logger:
    """Setup structured logging."""
    logger = logging.getLogger("ai_analyst")
    logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    logger.handlers = []

    handler = logging.StreamHandler(sys.stdout)

    if format_type == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))

    logger.addHandler(handler)
    return logger


# Global logger instance
logger = setup_logging()


def log_query(
    user_query: str,
    route: str,
    sql: Optional[str] = None,
    tables: Optional[list] = None,
    rows_returned: Optional[int] = None,
    execution_time_ms: Optional[float] = None,
    user_id: Optional[str] = None,
) -> None:
    """Log a data query event."""
    extra = {
        "query": user_query,
        "route": route,
        "sql": sql,
        "tables": tables,
        "rows_returned": rows_returned,
        "execution_time_ms": execution_time_ms,
        "user_id": user_id,
    }
    logger.info("Data query processed", extra={k: v for k, v in extra.items() if v is not None})


def log_llm_call(
    provider: str,
    model: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    latency_ms: Optional[float] = None,
    success: bool = True,
    error: Optional[str] = None,
) -> None:
    """Log an LLM API call."""
    total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
    extra = {
        "llm_provider": provider,
        "llm_model": model,
        "llm_tokens": total_tokens,
        "llm_latency_ms": latency_ms,
        "llm_success": success,
    }
    if error:
        logger.error(f"LLM call failed: {error}", extra=extra)
    else:
        logger.info("LLM call completed", extra=extra)


def log_security_event(
    event_type: str,
    details: Dict[str, Any],
    severity: str = "warning",
) -> None:
    """Log a security-related event."""
    extra = {
        "security_event": event_type,
        "security_details": details,
    }
    if severity == "error":
        logger.error(f"Security event: {event_type}", extra=extra)
    else:
        logger.warning(f"Security event: {event_type}", extra=extra)
