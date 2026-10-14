"""Build and verify a data-free, profile-specific security release/rollback.

Verification reads archives without extracting or executing their contents.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

PROFILE = 'browser-cookie-phase1'
MANIFEST = 'SECURITY-RELEASE.json'
MAX_CONTENT = 512 * 1024 * 1024
MAX_METADATA = 64 * 1024
SKIP = {'data', 'uploads', '_vendor', '__pycache__', 'node_modules', '.git', 'output', '.pytest_cache'}


def allowed(name):
    path = PurePosixPath(name)
    if not path.parts or path.as_posix() != name: return False
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or any(ord(c) < 32 for c in name) or any(p in SKIP or p.startswith(('.env', '.venv')) for p in path.parts) or path.name.startswith('test_') or 'fixture' in path.name.lower():
        return False
    if name == MANIFEST:
        return True
    if path.parts[0] in {'admin-backend', 'storefront-backend'}:
        return path.suffix == '.py' or path.name in {'requirements.txt', 'Dockerfile', '.dockerignore'}
    if path.parts[0] == 'scripts':
        return name == 'scripts/security/gingtto-release' or path.suffix in {'.py', '.sh', '.service', '.timer', '.conf', '.example', '.md'}
    if path.parts[0] == 'db':
        return path.suffix in {'.sql', '.md'}
    if path.parts[:2] == ('frontend', 'dist'):
        return path.suffix.lower() in {'.html', '.js', '.css', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.avif', '.ico', '.json', '.wav', '.mp3', '.woff', '.woff2', '.ttf'}
    return False


def required(channel):
    backend = 'admin-backend' if channel == 'admin' else 'storefront-backend'
    return {backend + '/' + n for n in ['app.py', 'security_core.py', 'security_settings.py', 'private_media.py', 'requirements.txt']} | {'frontend/dist/index.html', 'scripts/verify-security.py'}


def build(root, output, channel):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Existing release is preserved; choose a new filename')
    backend = 'admin-backend' if channel == 'admin' else 'storefront-backend'
    files = {}
    for folder in [backend, 'scripts', 'db', 'frontend/dist']:
        directory = root / folder
        if not directory.exists(): continue
        for path in sorted(directory.rglob('*')):
            name = path.relative_to(root).as_posix()
            if not allowed(name): continue
            if path.is_symlink():
                raise ValueError('Release sources must not contain symlinks')
            if path.is_file():
                raw = path.read_bytes()
                files[name] = raw
    if not required(channel) <= set(files):
        raise ValueError('Security-compatible release files are missing')
    if sum(map(len, files.values())) > 512 * 1024 * 1024:
        raise ValueError('Release exceeds the size limit')
    metadata = {'version': 1, 'profile': PROFILE, 'channel': channel, 'schema': 'browser-security-v1', 'deferred': ['private_attachments', 'login_protection_6_4', 'external_api'], 'files': {name: {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in files.items()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'x:gz') as archive:
        for name, raw in {**files, MANIFEST: json.dumps(metadata, sort_keys=True).encode()}.items():
            info = tarfile.TarInfo(name); info.size = len(raw); info.mode = 0o644
            archive.addfile(info, io.BytesIO(raw))
    output.chmod(0o600)
    return verify(output, channel)


class BoundedTarInfo(tarfile.TarInfo):
    def _proc_member(self, archive):
        # tarfile handles extension headers before yielding a member. Bound
        # them here so a malicious PAX/long-name allocation cannot precede the
        # normal member-size checks. No extension contents are ever executed.
        if self.type in {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK} and self.size > MAX_METADATA:
            raise ValueError('Release extension metadata exceeds the size limit')
        if self.type == tarfile.GNUTYPE_SPARSE: raise ValueError('Sparse release members are not supported')
        return super()._proc_member(archive)


class ExpandedBudget:
    def __init__(self, source):
        self.source, self.remaining = source, MAX_CONTENT + 32 * 1024 * 1024

    def read(self, amount=-1):
        raw = self.source.read(self.remaining + 1 if amount < 0 else min(amount, self.remaining + 1))
        self.remaining -= len(raw)
        if self.remaining < 0: raise ValueError('Release decompression exceeds the size limit')
        return raw


def verify(path, channel):
    if Path(path).stat().st_size > 256 * 1024 * 1024: raise ValueError('Compressed release exceeds the size limit')
    observed, metadata, total = {}, None, 0
    with gzip.open(path, 'rb') as compressed, tarfile.open(fileobj=ExpandedBudget(compressed), mode='r|', tarinfo=BoundedTarInfo) as archive:
        for item in archive:
            if len(observed) >= 20000 or item.name in observed or item.size < 0:
                raise ValueError('Invalid release member count or size')
            total += item.size
            if total > MAX_CONTENT: raise ValueError('Invalid release member count or size')
            if not item.isfile() or item.sparse is not None or not allowed(item.name):
                raise ValueError('Unsafe or data-bearing release entry')
            with archive.extractfile(item) as source:
                if item.name == MANIFEST:
                    if item.size > 16 * 1024 * 1024: raise ValueError('Release manifest exceeds the size limit')
                    metadata = json.loads(source.read())
                    observed[item.name] = None
                else:
                    checksum = hashlib.sha256(); remaining = item.size
                    while remaining:
                        raw = source.read(min(remaining, 1024 * 1024))
                        if not raw: raise ValueError('Truncated release member')
                        remaining -= len(raw); checksum.update(raw)
                    observed[item.name] = {'size': item.size, 'sha256': checksum.hexdigest()}
        if metadata is None:
            raise ValueError('Legacy backup is not security-compatible')
        if metadata.get('profile') != PROFILE or metadata.get('channel') != channel or metadata.get('schema') != 'browser-security-v1' or metadata.get('deferred') != ['private_attachments', 'login_protection_6_4', 'external_api']:
            raise ValueError('Incompatible security release profile')
        indexed = metadata.get('files', {})
        if not required(channel) <= set(indexed) or set(indexed) != set(observed) - {MANIFEST}:
            raise ValueError('Release manifest does not match its files')
        for name, value in indexed.items():
            if observed[name] != value:
                raise ValueError('Release checksum mismatch')
    checksum = hashlib.sha256()
    with Path(path).open('rb') as source:
        for raw in iter(lambda: source.read(1024 * 1024), b''): checksum.update(raw)
    return {'profile': PROFILE, 'channel': channel, 'files': len(indexed), 'sha256': checksum.hexdigest(), 'dataFree': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', choices=['admin', 'store'], required=True)
    parser.add_argument('--output')
    parser.add_argument('--verify')
    args = parser.parse_args()
    if bool(args.output) == bool(args.verify): parser.error('Choose exactly one of --output or --verify')
    print(json.dumps(verify(args.verify, args.channel) if args.verify else build(Path(__file__).resolve().parents[2], args.output, args.channel)))
