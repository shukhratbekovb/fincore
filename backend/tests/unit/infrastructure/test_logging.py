import os
import subprocess
from pathlib import Path
import json
import logging
import sys
from datetime import datetime

from backend.infrastructure.logging import JsonFormatter, logging_config, request_id_context


def test_json_log_includes_selected_metadata_and_omits_arbitrary_sensitive_extras():
    record = logging.LogRecord('backend.http', logging.INFO, __file__, 1, 'http_request', (), None)
    for name, value in {'method': 'POST', 'route': '/wallets/{wallet_id}', 'status_code': 201,
                        'duration_ms': 2.345, 'headers': {'Authorization': 'Bearer secret'},
                        'body': {'password': 'secret'}, 'query_string': 'token=secret'}.items():
        setattr(record, name, value)
    token = request_id_context.set('correlation-id')
    try:
        result = json.loads(JsonFormatter().format(record))
    finally:
        request_id_context.reset(token)
    assert result['request_id'] == 'correlation-id'
    assert result['route'] == '/wallets/{wallet_id}' and result['status_code'] == 201
    assert datetime.fromisoformat(result['timestamp']).utcoffset().total_seconds() == 0
    assert set(result) == {'timestamp', 'level', 'logger', 'message', 'request_id', 'method', 'route',
                           'status_code', 'duration_ms'}
    assert 'secret' not in str(result)


def test_exception_log_contains_type_and_frames_without_exception_message_or_locals():
    try:
        password = 'exception-and-local-secret'
        raise ValueError(password)
    except ValueError:
        record = logging.LogRecord('backend.worker', logging.ERROR, __file__, 1, 'operation_failed', (), sys.exc_info())
    result = json.loads(JsonFormatter().format(record))
    assert result['error_type'] == 'ValueError'
    assert result['traceback'] and set(result['traceback'][0]) == {'file', 'line', 'function'}
    assert 'exception-and-local-secret' not in str(result)
    assert 'request_id' not in result


def test_explicit_request_id_has_precedence_over_current_context():
    token = request_id_context.set('ambient-id')
    try:
        record = logging.LogRecord('backend.http', logging.INFO, __file__, 1, 'http_request', (), None)
        record.request_id = 'explicit-id'
        assert json.loads(JsonFormatter().format(record))['request_id'] == 'explicit-id'
    finally:
        request_id_context.reset(token)


def test_serialized_logging_config_emits_json_in_a_fresh_worker_and_suppresses_access_urls():
    config = json.loads(json.dumps(logging_config('WARNING')))
    program = """import json, logging, logging.config, sys
logging.config.dictConfig(json.loads(sys.argv[1]))
logging.getLogger('uvicorn.error').warning('worker_stopped')
logging.getLogger('uvicorn.access').info('GET /private-path?token=secret')
"""
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[3] / 'src')}
    result = subprocess.run([sys.executable, '-c', program, json.dumps(config)],
                            capture_output=True, text=True, check=True, env=environment)
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record['message'] == 'worker_stopped' and record['level'] == 'WARNING'
    assert record['logger'] == 'uvicorn.error'
    assert 'secret' not in result.stdout + result.stderr
