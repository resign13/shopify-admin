"""Private stdin-driven child for one detached order workbook."""
import json
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter


def peak_rss_bytes():
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return None
        return counters.PeakWorkingSetSize
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == 'darwin' else peak * 1024)


def snapshot_reader(sources):
    def read(url, attachment):
        try:
            return sources[(url, attachment)]
        except KeyError:
            raise PermissionError('Image source is not in the authorized snapshot') from None
    return read


class ImageReadStats:
    def __init__(self):
        self.lock = threading.Lock()
        self.values = {kind: {'attempts': 0, 'success': 0, 'errors': {}}
                       for kind in ('public_https', 'legacy', 'storage')}

    def wrap(self, read):
        def measured(url, source):
            kind = 'public_https' if source is None else 'legacy' if source.get('legacy_channel') else 'storage'
            with self.lock:
                self.values[kind]['attempts'] += 1
            try:
                result = read(url, source)
            except Exception as error:
                name = type(error).__name__
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name):
                    name = 'OtherError'
                with self.lock:
                    errors = self.values[kind]['errors']
                    errors[name] = errors.get(name, 0) + 1
                raise
            with self.lock:
                self.values[kind]['success'] += 1
            return result
        return measured

    def snapshot(self):
        with self.lock:
            return {kind: {'attempts': counts['attempts'], 'success': counts['success'],
                           'errors': dict(counts['errors'])} for kind, counts in self.values.items()}


def exception_type(error):
    # App image helpers suppress messages; retain only the originating type.
    for _ in range(8):
        nested = error.__cause__ or error.__context__
        if nested is None or nested is error:
            break
        error = nested
    name = type(error).__name__
    return name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name) else 'OtherError'


def main():
    worker_started = perf_counter()
    # Consume input before importing the application, so parent writes cannot
    # depend on startup checks completing.
    payload = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    os.environ['DB_SCHEMA_AUTO_MIGRATE'] = '0'
    import app as application
    import export_resources
    from export_image_cache import ExportImageError, stats_snapshot
    from flask import g

    # In test mode media locations are derived from the process temp root.
    # Preserve the parent's isolated test roots while keeping this worker's
    # export scratch files in its own temporary directory.
    if os.environ.get('APP_ENV') == 'test':
        application.media.roots = {key: Path(path) for key, path in payload['test_media_roots'].items()}
        application.media.uploads = {key: Path(path) for key, path in payload['test_media_uploads'].items()}

    original_stage = export_resources.stage
    timings = {}
    folder = Path(os.environ['TMPDIR'])
    counts = [0, 0]
    phase = ['workbook']
    image_stats = ImageReadStats()

    def progress(name, completed=None, total=None):
        phase[0] = name
        if completed is not None:
            counts[:] = [completed, total]
        value = {'phase': phase[0], 'completed': counts[0], 'total': counts[1],
                 'elapsed_ms': int((perf_counter() - worker_started) * 1000),
                 'image_read_stats': image_stats.snapshot(), 'image_cache_stats': stats_snapshot()}
        try:
            temporary = folder / 'progress.tmp'
            temporary.write_text(json.dumps(value), encoding='utf-8')
            temporary.replace(folder / 'progress.json')
        except OSError:
            pass

    @contextmanager
    def stage(name):
        started = perf_counter()
        succeeded = False
        try:
            with original_stage(name):
                yield
            succeeded = True
        finally:
            timings[name] = (perf_counter() - started) * 1000
            if name == 'images' and succeeded:
                progress('workbook')

    export_resources.stage = stage
    status = {}
    application._read_export_image = image_stats.wrap(application._read_export_image)
    try:
        with application.app.test_request_context('/'):
            g.export_progress = progress
            progress('workbook')
            g.export_sources = {(url, attachment): source for url, attachment, source in payload['sources']}
            application._export_image_source = snapshot_reader(g.export_sources)
            cache = export_resources.cache()
            for url, attachment in payload['denied']:
                cache[(url, attachment)] = None
            kind, orders = payload['kind'], payload['orders']
            if kind == 'combined':
                output = application.build_orders_export(orders, include_images=payload['include_images'])
            elif kind == 'split':
                output = application.build_orders_sheet_export(orders, include_images=payload['include_images'])
            elif kind == 'invoice':
                output = application.build_order_invoice_export(orders[0])
            else:
                raise RuntimeError('Invalid export kind')
            (folder / 'export.xlsx').write_bytes(output.getvalue())
    except ExportImageError as error:
        status = {'error': 'image_unavailable', 'exception_type': exception_type(error)}
    except ValueError as error:
        if payload.get('kind') == 'invoice':
            allowed = {'Please enter shipping fee before exporting PI', '请填写有效本单汇率', '本单汇率须为正数，最多六位小数'}
            status = {'error': 'invoice_invalid', 'message': str(error) if str(error) in allowed else 'Invalid invoice data'}
        else:
            status = {'error': 'export_failed'}
        status['exception_type'] = exception_type(error)
    except Exception as error:
        status = {'error': 'export_failed', 'exception_type': exception_type(error)}
    status.update({'pid': os.getpid(), 'phase': phase[0], 'completed': counts[0], 'total': counts[1],
                   'elapsed_ms': int((perf_counter() - worker_started) * 1000),
                   'image_read_stats': image_stats.snapshot(), 'image_cache_stats': stats_snapshot()})
    if 'images' in timings:
        status['image_ms'] = timings['images']
    try:
        peak = peak_rss_bytes()
    except (OSError, ImportError, AttributeError):
        peak = None
    if peak is not None:
        status['peak_rss_bytes'] = peak
    (folder / 'status.json').write_text(json.dumps(status, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
