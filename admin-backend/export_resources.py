"""Request-scoped, disk-backed export resources; no catalogue data is persisted."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import uuid
from flask import current_app, g, has_request_context


class ImageCache:
    def __init__(self):
        self.directory = TemporaryDirectory(prefix='gingtto-export-')
        self.entries = {}
        self.converted = {}

    def __contains__(self, key):
        return key in self.entries

    def __getitem__(self, key):
        path = self.entries[key]
        return path.read_bytes() if path else None

    def __setitem__(self, key, value):
        if value is None:
            self.entries[key] = None
        else:
            path = self.new_path()
            path.write_bytes(value)
            self.entries[key] = path

    def new_path(self):
        return Path(self.directory.name) / (uuid.uuid4().hex + '.image')

    def close(self):
        self.directory.cleanup()


def cache():
    value = getattr(g, 'export_disk_cache', None)
    if value is None:
        value = g.export_disk_cache = ImageCache()
    return value


def cleanup(error=None):
    value = g.pop('export_disk_cache', None)
    if value is not None:
        value.close()


@contextmanager
def stage(name):
    started = perf_counter()
    try:
        yield
    finally:
        if has_request_context():
            current_app.logger.info('export_stage request_id=%s phase=%s duration_ms=%.1f',
                getattr(g, 'request_id', ''), name, (perf_counter() - started) * 1000)
