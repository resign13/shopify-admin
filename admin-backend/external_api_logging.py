"""No machine credentials in application/development/Gunicorn access logs."""
import copy
import logging
import re
from collections.abc import Mapping

KEY = re.compile(r'gapi_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])')
QUERY = re.compile(r'(/api/external/[^?\s\"\']+)\?[^\s\"\']*')
REQUEST_QUERY = re.compile(r'(\b(?:GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)\s+\S+?)\?\S*(\s+HTTP/\d(?:\.\d)?)')


def clean(value):
    if not isinstance(value, str): return value
    # Strip request-line queries even when path/key bytes were percent-encoded.
    return KEY.sub('[REDACTED]', QUERY.sub(r'\1', REQUEST_QUERY.sub(r'\1\2', value)))


class CredentialFilter(logging.Filter):
    def filter(self, record):
        external = '/api/external/' in str(record.msg) or '/api/external/' in str(record.args)
        record.msg = clean(record.msg)
        if isinstance(record.args, Mapping):
            # Preserve Gunicorn SafeAtoms.__missing__ handling.
            args = copy.copy(record.args)
            for name, value in args.items():
                if str(name).lower() in {'authorization','cookie','{authorization}i','{cookie}i'}:
                    args[name] = '[REDACTED]'
                elif external and name == 'q': args[name] = ''
                else: args[name] = clean(value)
            record.args = args
        elif isinstance(record.args, tuple):
            record.args = tuple(clean(value) for value in record.args)
        record.exc_text = clean(record.exc_text)
        return True


def install(app):
    for logger in (app.logger, logging.getLogger('werkzeug'),
                   logging.getLogger('gunicorn.access'), logging.getLogger('gunicorn.error')):
        if not any(isinstance(f, CredentialFilter) for f in logger.filters):
            logger.addFilter(CredentialFilter())
