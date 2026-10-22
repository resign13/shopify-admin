"""Credential-free request timings and per-worker pool/resource measurements."""
import json
import os
import threading
import time
import uuid
from pathlib import Path
from flask import g, request

_lock = threading.Lock()
_last_sample = 0


def start():
    g.request_id = uuid.uuid4().hex
    g.request_started = time.perf_counter()


def record(app, response):
    global _last_sample
    response.headers['X-Request-ID'] = g.request_id
    event = {'event': 'request_timing', 'requestId': g.request_id,
        'route': request.url_rule.rule if request.url_rule else '<unknown>',
        'method': request.method, 'status': response.status_code,
        'durationMs': round((time.perf_counter()-g.request_started)*1000, 2)}
    app.logger.info('%s', json.dumps(event))
    now = time.monotonic()
    with _lock:
        if now - _last_sample < 60:
            return
        _last_sample = now
    import database_pool
    metrics = {'event': 'worker_resources', 'pid': os.getpid(), 'pools': database_pool.statistics()}
    try:
        values = Path('/proc/self/status').read_text().splitlines()
        metrics['rssKiB'] = int(next(v.split()[1] for v in values if v.startswith('VmRSS:')))
    except (OSError, StopIteration, ValueError):
        pass
    app.logger.info('%s', json.dumps(metrics))
