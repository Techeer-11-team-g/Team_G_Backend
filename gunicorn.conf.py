"""
Gunicorn configuration file.
https://docs.gunicorn.org/en/stable/settings.html
"""

import os

# Server socket
bind = os.getenv('GUNICORN_BIND', '0.0.0.0:8000')
workers = int(os.getenv('GUNICORN_WORKERS', '3'))
worker_class = 'sync'
timeout = 300

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
