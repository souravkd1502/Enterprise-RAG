"""JSON stdout logging with scoped identity context and defensive redaction.

Configure once at process startup. Bind identifiers only after JWT verification
or worker job-ownership validation. Logging context is never authorization.
See ``docs/logging.md`` for integration and data-handling rules.
"""

import json
import logging
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class _LogContext:
    tenant_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None


_context: ContextVar[_LogContext] = ContextVar("log_context", default=_LogContext())
_redactions = (
    # Authorization headers, including quoted dictionary/JSON representations.
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+"),
    # JWT-shaped values even without an Authorization prefix.
    re.compile(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    # Credential-bearing URLs: remove all userinfo, including encoded passwords.
    re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+@"),
    # Common key=value, JSON and dictionary credential representations.
    re.compile(
        r"""(?ix)(["']?\b(?:authorization|password|passwd|secret|token|api[_-]?key|
        access[_-]?key|secret[_-]?key|[a-z0-9_]+_(?:api_key|secret_key|access_key|token))
        \b["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;&}\]]+)"""
    ),
)


def _redact(text: str) -> str:
    """Mask recognizable credentials; callers must still exclude private data."""
    text = _redactions[0].sub("[REDACTED]", text)
    text = _redactions[1].sub("[REDACTED]", text)
    text = _redactions[2].sub(r"\1[REDACTED]@", text)
    return _redactions[3].sub(r"\1[REDACTED]", text)


@contextmanager
def log_context(
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
) -> Iterator[None]:
    """Bind trusted identifiers for a request/job and restore them on exit.

    Each scope replaces all three identifiers, so omitted fields cannot inherit
    another tenant's user. Tokens restore outer context even after exceptions.
    Context variables isolate concurrent asyncio tasks. New threads/processes
    require explicit context binding; spawned tasks may inherit their creator's
    context and must not outlive a request without an explicit job scope.
    """
    context = _LogContext(tenant_id, user_id, request_id)
    for value in asdict(context).values():
        if value is not None and (
            not isinstance(value, str)
            or not value
            or len(value) > 256
            or any(
                character.isspace() or not character.isprintable()
                for character in value
            )
        ):
            raise ValueError(
                "Log identifiers must be nonempty strings of up to 256 visible characters"
            )
    if user_id is not None and tenant_id is None:
        raise ValueError("A user log context requires a tenant identifier")
    token = _context.set(context)
    try:
        yield
    finally:
        _context.reset(token)


class JsonFormatter(logging.Formatter):
    """Serialize an allowlist of fields, never arbitrary LogRecord extras.

    Exception output contains type and frame locations only. Exception messages,
    source lines and locals are omitted because they can contain credentials or
    document content. Records are not mutated, preserving other handlers' input.
    """

    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
            **asdict(_context.get()),
        }
        if record.exc_info and record.exc_info[0] is not None:
            frames = []
            traceback = record.exc_info[2]
            while traceback is not None:
                code = traceback.tb_frame.f_code
                frames.append(
                    {
                        "file": Path(code.co_filename).name,
                        "function": code.co_name,
                        "line": traceback.tb_lineno,
                    }
                )
                traceback = traceback.tb_next
            event["exception"] = {"type": record.exc_info[0].__name__, "frames": frames}
        return json.dumps(event, ensure_ascii=True, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    """Install one JSON stdout handler using the configured LOG_LEVEL.

    The process entry point owns root logging: existing root handlers are closed
    and replaced. Repeated startup calls do not accumulate handlers. Configure
    before starting concurrent work; named third-party handlers are untouched.
    This function neither loads settings nor reads environment variables.
    """
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("Unsupported log level")
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # Command bodies can include account hashes, email addresses and document data.
    logging.getLogger("pymongo.command").setLevel(logging.WARNING)
