import json
import logging
import logging.config
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone


request_id_context: ContextVar[str | None] = ContextVar('request_id', default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'timestamp': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        request_id = getattr(record, 'request_id', None) or request_id_context.get()
        if request_id:
            payload['request_id'] = request_id
        for field in ('method', 'route', 'status_code', 'duration_ms', 'error_type'):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info and record.exc_info[0] is not None:
            payload['error_type'] = record.exc_info[0].__name__
            payload['traceback'] = [
                {'file': frame.filename, 'line': frame.lineno, 'function': frame.name}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def logging_config(level: str = 'INFO') -> dict:
    # Serializable configuration also reaches Uvicorn's spawned worker processes.
    return {
        'version': 1, 'disable_existing_loggers': False,
        'formatters': {'json': {'()': 'backend.infrastructure.logging.JsonFormatter'}},
        'handlers': {'stdout': {'class': 'logging.StreamHandler', 'stream': 'ext://sys.stdout', 'formatter': 'json'}},
        'root': {'handlers': ['stdout'], 'level': level},
        'loggers': {
            'uvicorn': {'handlers': [], 'propagate': True, 'level': level},
            'uvicorn.error': {'handlers': [], 'propagate': True, 'level': level},
            'uvicorn.access': {'handlers': [], 'propagate': False, 'level': 'CRITICAL'},
        },
    }


def configure_logging(level: str = 'INFO') -> None:
    logging.config.dictConfig(logging_config(level))
