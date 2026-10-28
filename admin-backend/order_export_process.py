"""Run detached workbook construction in a bounded child process."""
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
from flask import current_app, g
import export_resources


class ExportTimeout(Exception):
    def __init__(self, progress=None, image_read_stats=None, worker_pid=None, image_cache_stats=None):
        super().__init__('Export timed out')
        self.progress = progress or {}
        self.image_read_stats = image_read_stats or {}
        self.worker_pid = worker_pid
        self.image_cache_stats = image_cache_stats or {}


class ExportFailed(Exception):
    def __init__(self, metadata=None):
        super().__init__('Export failed')
        self.metadata = safe_worker_metadata(metadata)
        self.worker_pid = self.metadata.get('pid')
        self.progress = {key: self.metadata[key] for key in ('phase', 'completed', 'total', 'elapsed_ms') if key in self.metadata}
        self.image_read_stats = self.metadata.get('image_read_stats', {})
        self.image_cache_stats = self.metadata.get('image_cache_stats', {})
        self.error_type = self.metadata.get('exception_type')
        self.phase = self.metadata.get('phase')


class ImageUnavailable(ExportFailed):
    pass


class InvoiceInvalid(Exception):
    pass


_SOURCE_FIELDS = ('storage_channel', 'storage_key', 'byte_size', 'sha256',
                  'legacy_channel', 'legacy_path', 'legacy_key')


def safe_image_stats(value):
    if not isinstance(value, dict):
        return {}
    clean = {}
    for kind in ('public_https', 'legacy', 'storage'):
        item = value.get(kind)
        if not isinstance(item, dict):
            return {}
        attempts, success, errors = item.get('attempts'), item.get('success'), item.get('errors')
        if (type(attempts) is not int or type(success) is not int or not 0 <= success <= attempts <= 100000000
                or not isinstance(errors, dict)):
            return {}
        safe_errors = {}
        for name, count in errors.items():
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name) or type(count) is not int or not 0 <= count <= 100000000:
                return {}
            safe_errors[name] = count
        if sum(safe_errors.values()) + success > attempts:
            return {}
        clean[kind] = {'attempts': attempts, 'success': success, 'errors': safe_errors}
    return clean


def safe_cache_stats(value):
    if not isinstance(value, dict):
        return {}
    keys = ('raw_hits', 'raw_misses', 'converted_hits', 'converted_misses', 'lock_waits', 'errors')
    if any(type(value.get(key)) is not int or not 0 <= value[key] <= 100000000 for key in keys):
        return {}
    return {key: value[key] for key in keys}


def safe_worker_metadata(value):
    if not isinstance(value, dict):
        return {}
    clean = {}
    for key in ('pid', 'completed', 'total', 'elapsed_ms', 'peak_rss_bytes'):
        number = value.get(key)
        if type(number) is int and 0 <= number <= 10 ** 15:
            clean[key] = number
    if value.get('phase') in {'images', 'workbook'}:
        clean['phase'] = value['phase']
    name = value.get('exception_type')
    if isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name):
        clean['exception_type'] = name
    image_ms = value.get('image_ms')
    if type(image_ms) in (int, float) and 0 <= image_ms <= 100000000:
        clean['image_ms'] = image_ms
    for key, sanitize in (('image_read_stats', safe_image_stats), ('image_cache_stats', safe_cache_stats)):
        stats = sanitize(value.get(key))
        if stats:
            clean[key] = stats
    return clean


def _sources():
    sources = getattr(g, 'export_sources', {})
    authorized = []
    for (url, attachment), source in sources.items():
        value = None if source is None else {key: source[key] for key in _SOURCE_FIELDS if key in source}
        authorized.append([url, attachment, value])
    disk_cache = getattr(g, 'export_disk_cache', None)
    denied = [[url, attachment] for (url, attachment), path in disk_cache.entries.items() if path is None] if disk_cache else []
    return authorized, denied


def _run_worker(payload, *, timeout=90, command=None):
    """Return output bytes and child metadata; always reap before temp cleanup."""
    with TemporaryDirectory(prefix='gingtto-export-worker-') as directory:
        folder = Path(directory)
        env = os.environ.copy()
        env.update({'TMP': directory, 'TEMP': directory, 'TMPDIR': directory, 'DB_SCHEMA_AUTO_MIGRATE': '0'})
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        args = command if command is not None else [sys.executable, str(Path(__file__).with_name('order_export_worker.py'))]
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   cwd=str(Path(__file__).resolve().parent), env=env, close_fds=True)

        def write_input():
            try:
                with process.stdin as stream:
                    stream.write(encoded)
            except (BrokenPipeError, OSError, ValueError):
                pass

        writer = threading.Thread(target=write_input, daemon=True)
        writer.start()
        try:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                progress = {}
                stats = {}
                cache_stats = {}
                try:
                    candidate = json.loads((folder / 'progress.json').read_text(encoding='utf-8'))
                    if (candidate.get('phase') in {'images', 'workbook'}
                            and all(type(candidate.get(key)) is int and 0 <= candidate[key] <= 100000000
                                    for key in ('completed', 'total', 'elapsed_ms'))
                            and candidate['completed'] <= candidate['total']):
                        progress = {key: candidate[key] for key in ('phase', 'completed', 'total', 'elapsed_ms')}
                        stats = safe_image_stats(candidate.get('image_read_stats'))
                        cache_stats = safe_cache_stats(candidate.get('image_cache_stats'))
                except (OSError, ValueError, TypeError, AttributeError):
                    pass
                raise ExportTimeout(progress, stats, process.pid, cache_stats) from None
        finally:
            if process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    process.wait()
            writer.join()
        metadata = {'pid': process.pid}
        try:
            candidate = json.loads((folder / 'progress.json').read_text(encoding='utf-8'))
            metadata.update(safe_worker_metadata(candidate))
        except (OSError, ValueError, TypeError):
            pass
        if process.returncode != 0:
            raise ExportFailed(metadata)
        try:
            status = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
            metadata.update(safe_worker_metadata(status))
            if status.get('error') == 'image_unavailable':
                raise ImageUnavailable(metadata)
            if status.get('error') == 'invoice_invalid':
                raise InvoiceInvalid(status.get('message', 'Invalid invoice data'))
            if status.get('error'):
                raise ExportFailed(metadata)
            output = (folder / 'export.xlsx').read_bytes()
        except (OSError, ValueError, TypeError, AttributeError):
            raise ExportFailed(metadata) from None
        return output, status


def build(kind, orders, *, include_images=True):
    sources, denied = _sources()
    timeout = float(os.environ.get('ORDER_EXPORT_TIMEOUT_SECONDS', '90'))
    if not 0 < timeout <= 90:
        raise RuntimeError('Invalid export timeout')
    payload = {'kind': kind, 'orders': orders, 'include_images': include_images,
               'sources': sources, 'denied': denied}
    if os.environ.get('APP_ENV') == 'test':
        media = current_app.extensions['media']
        payload['test_media_roots'] = {key: str(path) for key, path in media.roots.items()}
        payload['test_media_uploads'] = {key: str(path) for key, path in media.uploads.items()}
    try:
        output, metadata = _run_worker(payload, timeout=timeout)
    except ExportTimeout as error:
        if error.image_cache_stats:
            current_app.logger.info('export_image_cache_stats request_id=%s counts=%s',
                                    getattr(g, 'request_id', ''), json.dumps(error.image_cache_stats, separators=(',', ':')))
        if error.image_read_stats:
            current_app.logger.info('export_image_read_stats request_id=%s counts=%s',
                                    getattr(g, 'request_id', ''), json.dumps(error.image_read_stats, separators=(',', ':')))
        raise
    cache_stats = safe_cache_stats(metadata.get('image_cache_stats'))
    if cache_stats:
        current_app.logger.info('export_image_cache_stats request_id=%s counts=%s',
                                getattr(g, 'request_id', ''), json.dumps(cache_stats, separators=(',', ':')))
    image_ms = metadata.get('image_ms')
    if isinstance(image_ms, (int, float)):
        current_app.logger.info('export_stage request_id=%s phase=images duration_ms=%.1f',
                                getattr(g, 'request_id', ''), image_ms)
    stats = safe_image_stats(metadata.get('image_read_stats'))
    if stats:
        current_app.logger.info('export_image_read_stats request_id=%s counts=%s',
                                getattr(g, 'request_id', ''), json.dumps(stats, separators=(',', ':')))
    peak = metadata.get('peak_rss_bytes')
    if isinstance(peak, int) and peak >= 0:
        current_app.logger.info('export_worker request_id=%s peak_rss_bytes=%d',
                                getattr(g, 'request_id', ''), peak)
    return io.BytesIO(output)
