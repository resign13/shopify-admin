# Production service must use --config gunicorn.conf.py; not the dev server.
import os
import re
bind = os.environ.get('GUNICORN_BIND', '127.0.0.1:5302')
if not re.fullmatch(r'(127\.0\.0\.1|\[::1\]):[0-9]{1,5}',bind) or not 1 <= int(bind.rsplit(':',1)[1]) <= 65535: raise RuntimeError('Application sockets must be loopback-only')
workers = int(os.environ.get('GUNICORN_WORKERS', '4'))
if not 1 <= workers <= 16: raise RuntimeError('Worker count must be between 1 and 16')
worker_class = 'gthread'
threads = 2
timeout = 120
graceful_timeout = 30
max_requests = 2000
max_requests_jitter = 200
limit_request_line = 16384
limit_request_field_size = 8190
# Werkzeug validates proxy peers; Gunicorn must not independently trust headers.
forwarded_allow_ips = ''
secure_scheme_headers = {}
accesslog = '-'
errorlog = '-'
access_log_format = '%(t)s method=%(m)s status=%(s)s duration_us=%(D)s'
capture_output = False
umask = 0o027
