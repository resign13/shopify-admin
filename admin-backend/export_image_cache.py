"""Private cross-process export image cache, keyed by existing source identities."""
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
from urllib.parse import quote
import uuid


class ExportImageError(Exception):
    def __init__(self):
        super().__init__('Order image could not be read')


@dataclass(frozen=True)
class Entry:
    data: bytes
    token: str


class ImageBytes(bytes):
    """Keep the original cache generation until the request scratch copy is made."""
    def __new__(cls, data, token):
        value = super().__new__(cls, data)
        value.cache_token = token
        return value


_variant = threading.local()
_CLOUDINARY_UPLOAD = re.compile(
    r'(?P<prefix>https://res\.cloudinary\.com/[A-Za-z0-9_-]+/image/upload/)'
    r'(?P<asset>v[0-9]+/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp))'
)


@contextmanager
def image_variant(pixels):
    """Set only the current export read's existing product/attachment limit."""
    if pixels not in (640, 1600):
        raise ValueError('Invalid export image variant')
    previous = getattr(_variant, 'pixels', None)
    _variant.pixels = pixels
    try:
        yield
    finally:
        _variant.pixels = previous


def export_source_url(value):
    """Resize only explicit unsigned public Cloudinary original upload URLs.

    c_limit preserves aspect ratio without cropping or upscaling. The original
    extension is retained; no quality, format or transparency transform is set.
    Other deliveries, existing transforms, signatures and query URLs stay intact.
    """
    pixels = getattr(_variant, 'pixels', None)
    match = _CLOUDINARY_UPLOAD.fullmatch(value) if pixels is not None else None
    if match is None:
        return value
    return f"{match['prefix']}c_limit,w_{pixels},h_{pixels}/{match['asset']}"


_stats_lock = threading.Lock()
_stats = {key: 0 for key in ('raw_hits', 'raw_misses', 'converted_hits', 'converted_misses', 'lock_waits', 'errors')}


def _count(key):
    with _stats_lock:
        _stats[key] += 1


def stats_snapshot():
    with _stats_lock:
        return dict(_stats)


def source_identity(value, source):
    if source is None:
        return ['https', value]
    if source.get('legacy_path'):
        path = Path(source['legacy_path']).resolve()
        info = path.stat()
        return ['legacy-file', source['legacy_channel'], str(path), info.st_size, info.st_mtime_ns, info.st_ino]
    if source.get('legacy_channel'):
        return ['legacy-object', source['legacy_channel'], os.environ.get('R2_BUCKET', ''), source['legacy_key']]
    return ['storage', source['storage_channel'], source['storage_key'], source['byte_size'], source['sha256']]


def _private_directory(path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        user = os.environ.get('USERDOMAIN', '') + '\\' + os.environ['USERNAME']
        result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', user + ':(OI)(CI)F',
                                 '*S-1-5-18:(OI)(CI)F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise OSError('Export cache permissions could not be set')
    else:
        path.chmod(0o700)


class SharedImageCache:
    LOCKS = 64

    def __init__(self, directory, *, max_bytes=512 * 1024 * 1024, ttl_seconds=86400):
        self.directory = Path(directory).resolve()
        self.max_bytes, self.ttl_seconds = int(max_bytes), float(ttl_seconds)
        if self.max_bytes <= 0 or self.ttl_seconds <= 0:
            raise ValueError('Invalid export image cache limits')
        _private_directory(self.directory)
        self.database = self.directory / 'index.sqlite3'
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT UNIQUE NOT NULL,
                file_id TEXT, size INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL DEFAULT 0,
                accessed REAL NOT NULL DEFAULT 0)''')
        if os.name != 'nt':
            self.database.chmod(0o600)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def _lock(self, slot, *, wait=True):
        # A bounded set of stable lock files avoids unlink/recreate lock races.
        path = self.directory / ('lock-' + str(slot % self.LOCKS))
        stream = path.open('a+b')
        if os.name != 'nt':
            os.chmod(path, 0o600)
        if stream.seek(0, 2) == 0:
            stream.write(b'0')
            stream.flush()
        acquired = False
        started = time.monotonic()
        counted = False
        try:
            while True:
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    if not wait:
                        break
                    if not counted:
                        _count('lock_waits')
                        counted = True
                    if time.monotonic() - started > 120:
                        raise TimeoutError('Export image cache wait timed out') from None
                    time.sleep(0.02)
            yield acquired
        finally:
            if acquired:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()

    def _path(self, file_id):
        return self.directory / (file_id + '.image')

    def get(self, identity, build, *, kind='raw', ttl_seconds=None):
        ttl = self.ttl_seconds if ttl_seconds is None else min(self.ttl_seconds, float(ttl_seconds))
        if ttl <= 0:
            raise ValueError('Invalid export image cache TTL')
        key = json.dumps(identity, ensure_ascii=True, separators=(',', ':'), default=str)
        while True:
            with self._db() as db:
                db.execute('INSERT OR IGNORE INTO images(source) VALUES (?)', (key,))
                slot = db.execute('SELECT id FROM images WHERE source=?', (key,)).fetchone()['id']
            with self._lock(slot):
                with self._db() as db:
                    row = db.execute('SELECT * FROM images WHERE source=?', (key,)).fetchone()
                # Pruning may have removed the slot while this caller waited.
                if row is None or row['id'] != slot:
                    continue
                now = time.time()
                if row['file_id'] and row['expires'] > now:
                    try:
                        data = self._path(row['file_id']).read_bytes()
                        if len(data) != row['size']:
                            raise OSError('Incomplete cache file')
                    except OSError:
                        pass
                    else:
                        with self._db() as db:
                            db.execute('UPDATE images SET accessed=? WHERE id=?', (now, slot))
                        _count(kind + '_hits')
                        return Entry(data, row['file_id'])
                _count(kind + '_misses')
                try:
                    # No SQLite transaction or connection spans the read/convert.
                    data = build()
                    if not isinstance(data, bytes) or not data:
                        raise ValueError('Empty image')
                    file_id = uuid.uuid4().hex
                    if len(data) <= self.max_bytes:
                        temporary = self.directory / (file_id + '.tmp')
                        try:
                            with temporary.open('xb') as output:
                                if os.name != 'nt':
                                    os.chmod(temporary, 0o600)
                                output.write(data)
                                output.flush()
                            temporary.replace(self._path(file_id))
                            with self._db() as db:
                                db.execute('UPDATE images SET file_id=?,size=?,expires=?,accessed=? WHERE id=?',
                                           (file_id, len(data), time.time() + ttl, now, slot))
                        finally:
                            temporary.unlink(missing_ok=True)
                        if row['file_id']:
                            self._path(row['file_id']).unlink(missing_ok=True)
                    else:
                        with self._db() as db:
                            db.execute('DELETE FROM images WHERE id=?', (slot,))
                        if row['file_id']:
                            self._path(row['file_id']).unlink(missing_ok=True)
                except Exception:
                    _count('errors')
                    # Do not cache failures; subsequent requests can recover.
                    raise
            self.prune()
            return Entry(data, file_id)

    def prune(self):
        with self._db() as db:
            rows = db.execute('SELECT * FROM images ORDER BY accessed,id').fetchall()
        total = sum(row['size'] for row in rows)
        now = time.time()
        for row in rows:
            if row['expires'] > now and total <= self.max_bytes:
                continue
            with self._lock(row['id'], wait=False) as acquired:
                if not acquired:
                    continue
                with self._db() as db:
                    current = db.execute('SELECT * FROM images WHERE id=?', (row['id'],)).fetchone()
                    if current is None or current['file_id'] != row['file_id'] or current['accessed'] != row['accessed']:
                        continue
                    db.execute('DELETE FROM images WHERE id=?', (row['id'],))
                if row['file_id']:
                    self._path(row['file_id']).unlink(missing_ok=True)
                total -= row['size']
        # A killed worker may leave an unindexed atomic-write file. Only remove
        # old orphans, outside the maximum lock/build duration.
        with self._db() as db:
            live = {row[0] for row in db.execute('SELECT file_id FROM images WHERE file_id IS NOT NULL')}
        for path in self.directory.glob('*'):
            if path.suffix not in {'.tmp', '.image'} or path.stem in live:
                continue
            try:
                if path.stat().st_mtime < now - 300:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass


def cache_directory():
    root = Path(os.environ.get('ORDER_EXPORT_IMAGE_CACHE_DIR', str(Path(__file__).resolve().parent / 'data' / 'order-export-images')))
    if os.environ.get('APP_ENV') == 'test':
        database = os.environ.get('PGDATABASE') or 'unit_test'
        if not database.endswith('_test'):
            raise ValueError('Export test cache requires a *_test database namespace')
        root = root / ('db-' + quote(database, safe=''))
    return root.resolve()


@lru_cache(maxsize=8)
def _configured(directory, max_bytes, ttl):
    return SharedImageCache(directory, max_bytes=max_bytes, ttl_seconds=ttl)


def shared_cache():
    return _configured(str(cache_directory()), int(os.environ.get('ORDER_EXPORT_IMAGE_CACHE_MAX_BYTES', str(512 * 1024 ** 2))),
                       float(os.environ.get('ORDER_EXPORT_IMAGE_CACHE_TTL_SECONDS', '86400')))


def source_ttl(source):
    """Mutable URL/object names have bounded staleness, not immediate invalidation."""
    if source is None or (source.get('legacy_channel') and not source.get('legacy_path')):
        ttl = float(os.environ.get('ORDER_EXPORT_IMAGE_CACHE_SOURCE_TTL_SECONDS', '300'))
        if not 0 < ttl <= 300:
            raise ValueError('Invalid unversioned export source TTL')
        return ttl
    return None
