"""
Gunicorn configuration file.
https://docs.gunicorn.org/en/stable/settings.html
"""

import multiprocessing
import os

# Server socket
bind = os.getenv('GUNICORN_BIND', '0.0.0.0:8000')

# Workers - (2 * CPU cores) + 1 권장
# gevent 사용 시 더 적은 워커로도 높은 동시성 처리 가능
cpu_count = multiprocessing.cpu_count()
workers = int(os.getenv('GUNICORN_WORKERS', str(cpu_count * 2 + 1)))

# Worker class - gevent for async I/O (requires gevent package)
worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'gevent')

# Connections per worker (gevent/eventlet only)
worker_connections = int(os.getenv('GUNICORN_WORKER_CONNECTIONS', '1000'))

# Timeout
timeout = 300

# Graceful timeout
graceful_timeout = 30

# Keep-alive connections
keepalive = 5

# Logging
loglevel = 'info'
errorlog = '-'  # stderr
accesslog = '-'  # stdout

# JSON 형식 액세스 로그
access_log_format = (
    '{'
    '"time":"%(t)s",'
    '"remote_addr":"%(h)s",'
    '"method":"%(m)s",'
    '"uri":"%(U)s",'
    '"query":"%(q)s",'
    '"status":%(s)s,'
    '"body_bytes_sent":%(B)s,'
    '"request_time":%(D)s,'
    '"http_referrer":"%(f)s",'
    '"http_user_agent":"%(a)s",'
    '"pid":%(p)s'
    '}'
)

# Process naming
proc_name = 'team-g-backend'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (if needed)
# keyfile = None
# certfile = None
