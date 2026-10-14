"""Root-installed, bounded release controller. Never execute release code as root.

Production CLI has no configurable paths or arbitrary command argument. Application
code, dependencies and read-only checks execute in separate non-root systemd units.
Database backups are read-only; rollback switches compatible code, never a database.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import tarfile
import time
from urllib.request import build_opener, ProxyHandler
import uuid

PROFILE = 'browser-cookie-phase1'
APPS = {'admin': ('shopify-admin', 'admin-backend', 'smawell-admin-api', 5302),
        'store': ('shopify', 'storefront-backend', 'smawell-store-api', 5301)}
MAX_ARCHIVE = 256 * 1024 * 1024


@dataclass(frozen=True)
class Config:
    base: Path = Path('/opt/smawell')
    state: Path = Path('/var/lib/gingtto-release')
    config: Path = Path('/etc/gingtto')
    database: str = 'smawell_admin'
    deploy_user: str = 'gingtto-deploy'
    build_user: str = 'gingtto-build'

    def app(self, channel):
        if channel not in APPS: raise ValueError('Invalid application')
        repo, backend, service, port = APPS[channel]
        return {'channel': channel, 'backend': backend, 'service': service, 'port': port,
                'user': 'gingtto-' + channel, 'group': 'gingtto-' + channel,
                'primary': self.base / repo / backend,
                'current': self.base / 'current' / channel,
                'releases': self.base / 'releases' / channel,
                'assets': self.base / 'public-assets' / channel,
                'env': self.config / 'runtime' / (channel + '.env'),
                'security_env': self.config / 'runtime' / (channel + '.security.env')}


def archive_library():
    path = Path(__file__).with_name('build_release.py')
    spec = importlib.util.spec_from_file_location('gingtto_release_archive', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def stage_name(channel, value):
    if channel not in APPS or not re.fullmatch(channel + r'-[1-9][0-9]{0,18}-[1-9][0-9]{0,4}', value):
        raise ValueError('Invalid incoming release identifier')
    return value


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def env_values(raw):
    """Canonical one-line EnvironmentFiles, also understood by db.load_env_file.

    Reject ambiguous overrides instead of silently changing which credential or
    switch wins between systemd and the application's file loader.
    """
    values = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        if '=' not in line: raise ValueError('Invalid canonical runtime configuration')
        key, value = line.split('=', 1); key = key.strip()
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or key in values:
            raise ValueError('Duplicate or invalid runtime configuration key')
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]: raise ValueError('Invalid configuration quoting')
            value = value[1:-1]
        if any(c in value for c in ['\\', '\x00', '\r', '\n']):
            raise ValueError('Noncanonical multiline/escaped configuration')
        if value != value.strip('"').strip("'"):
            raise ValueError('Configuration quoting differs between loaders')
        values[key] = value
    return values


def runtime_values(app_raw, security_raw, database, channel):
    business, security = env_values(app_raw), env_values(security_raw)
    if business.keys() & security.keys(): raise ValueError('Runtime configuration has multiple authorities')
    for key in business:
        if key.startswith(('PG', 'POSTGRES_', 'DB_', 'SECURITY_', 'MIGRATION_')) or key == 'APP_ENV':
            raise ValueError('Database/security configuration must be isolated')
    if any(key.startswith('ORDER_VOICE_') for key in security):
        raise ValueError('Voice configuration must have one application authority')
    values = {**business, **security}
    if values.get('GUNICORN_CMD_ARGS'): raise ValueError('Gunicorn command overrides are not supported')
    if values.get('GUNICORN_BIND', '127.0.0.1:' + str(APPS[channel][3])) != '127.0.0.1:' + str(APPS[channel][3]):
        raise ValueError('Application must bind its fixed loopback endpoint')
    if security.get('PGHOST') not in {'127.0.0.1', '::1'}:
        raise ValueError('Runtime database must use the local endpoint')
    for key, expected in {'APP_ENV': 'production', 'DB_SCHEMA_AUTO_MIGRATE': '0',
            'SECURITY_ATTACHMENT_MODE': 'legacy', 'SECURITY_LOGIN_PROTECTION_ENABLED': '0',
            'PGDATABASE': database}.items():
        if security.get(key) != expected: raise ValueError('Runtime profile mismatch')
    if channel == 'admin' and (business.get('ORDER_VOICE_ENABLED') not in {'0', '1'} or
            len(business.get('ORDER_VOICE_CURSOR_SECRET', '')) < 32 or
            business.get('ORDER_VOICE_CURSOR_SECRET', '').startswith(('REPLACE_', 'CHANGE_'))):
        raise ValueError('Canonical voice configuration required')
    return values


def storage_probe(app, target):
    """Fixed, metadata-only probe executed as the actual runtime UID.

    No canary files, reads of business content, chmod or database writes. The
    transient unit exposes exactly the persistent writable paths being checked.
    """
    base = Path(target) / app['backend']
    directories = [app['primary'] / 'data', app['primary'] / 'uploads']
    return f'''import os
from pathlib import Path
assert os.geteuid()!=0, 'Runtime identity must be non-root'
base=Path({str(base)!r})
assert not os.access(base,os.W_OK), 'Runtime code must not be writable'
for name in ['.env','.env.security']:
    path=base/name
    assert path.is_file() and os.access(path,os.R_OK) and not os.access(path,os.W_OK), 'Runtime configuration access is not ready'
for name in {[str(p) for p in directories]!r}:
    path=Path(name)
    assert path.is_dir() and os.access(path,os.R_OK|os.W_OK|os.X_OK), 'Persistent directory access is not ready'
cache=Path({str(directories[0] / 'image-cache')!r})
if cache.exists():
    assert not cache.is_symlink() and cache.is_dir() and os.access(cache,os.R_OK|os.W_OK|os.X_OK), 'Image cache access is not ready'
    for entry in cache.iterdir():
        assert not entry.is_symlink(), 'Image cache contains a symbolic link'
        if entry.is_file():
            needed=os.R_OK | (os.W_OK if entry.suffix=='.lock' else 0)
            assert os.access(entry,needed), 'Existing cache file access is not ready'
'''


class Files:
    def __init__(self, cfg): self.cfg = cfg

    def trusted(self, path, *, directory=False):
        path = Path(path)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('Untrusted controller path')
        if directory != stat.S_ISDIR(info.st_mode): raise ValueError('Invalid controller path type')
        if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError('Invalid controller file')
        for parent in path.parents:
            meta = parent.lstat()
            if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
                raise PermissionError('Untrusted controller parent')
        return info

    def directory(self, path, mode=0o755):
        path = Path(path)
        if not path.exists():
            self.trusted(path.parent, directory=True)
            path.mkdir(mode=mode)
        self.trusted(path, directory=True)
        return path

    def json_write(self, path, value, mode=0o600):
        path = Path(path); self.trusted(path.parent, directory=True)
        temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def json_read(self, path):
        self.trusted(path)
        return json.loads(Path(path).read_text(encoding='utf-8'))

    def spool(self, channel, incoming, deploy_uid):
        # Descriptor-relative traversal protects every untrusted stage component.
        basefd = os.open(self.cfg.base / 'incoming', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stagefd = filefd = None
        try:
            for fd in [basefd]:
                info = os.fstat(fd)
                if info.st_uid != deploy_uid or info.st_mode & 0o077: raise PermissionError('Incoming ownership/mode')
            stagefd = os.open(stage_name(channel, incoming), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=basefd)
            info = os.fstat(stagefd)
            if info.st_uid != deploy_uid or info.st_mode & 0o077: raise PermissionError('Stage ownership/mode')
            filefd = os.open('release.tar.gz', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=stagefd)
            info = os.fstat(filefd)
            if info.st_uid != deploy_uid or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077 or not 0 < info.st_size <= MAX_ARCHIVE:
                raise PermissionError('Incoming archive ownership/type/size')
            path = self.cfg.state / 'spool' / (uuid.uuid4().hex + '.tar.gz')
            with path.open('xb') as output:
                size = 0
                while block := os.read(filefd, 1024 * 1024):
                    size += len(block)
                    if size > MAX_ARCHIVE: raise ValueError('Incoming archive grew beyond limit')
                    output.write(block)
                output.flush(); os.fsync(output.fileno())
            path.chmod(0o600)
            return path
        finally:
            for fd in (filefd, stagefd, basefd):
                if fd is not None: os.close(fd)

    def extract(self, archive, target):
        self.directory(target)
        with tarfile.open(archive, 'r:gz') as bundle:
            # Archive was verified from a sealed root-owned copy. No tarfile
            # extraction helpers, links, owners or mode metadata are applied.
            for item in bundle:
                path = target / item.name
                for directory in reversed(path.parent.relative_to(target).parents):
                    if str(directory) != '.': self.directory(target / directory)
                self.directory(path.parent)
                with path.open('xb') as output, bundle.extractfile(item) as source:
                    while block := source.read(1024 * 1024): output.write(block)
                path.chmod(0o644)

    def link_runtime(self, app, target):
        backend = target / app['backend']
        for name, value in {'.env': app['env'], '.env.security': app['security_env'],
                            'data': app['primary'] / 'data', 'uploads': app['primary'] / 'uploads'}.items():
            if not value.exists(): raise FileNotFoundError('Persistent runtime input missing')
            (backend / name).symlink_to(value, target_is_directory=name in {'data', 'uploads'})

    def seal(self, app, target):
        managed = {str(target / app['backend'] / name): value for name, value in {
            '.env': app['env'], '.env.security': app['security_env'], 'data': app['primary'] / 'data',
            'uploads': app['primary'] / 'uploads'}.items()}
        venv = target / app['backend'] / '.venv'
        for directory, dirs, files in os.walk(target, followlinks=False):
            for path in [Path(directory), *[Path(directory) / n for n in dirs + files]]:
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    resolved = path.resolve()
                    valid = managed.get(str(path)) == resolved
                    if path.is_relative_to(venv):
                        valid |= resolved.is_relative_to(venv) or (resolved.parent == Path('/usr/bin') and re.fullmatch(r'python3(?:\.[0-9]+)?', resolved.name) is not None)
                    if not valid: raise ValueError('Unexpected dependency symlink')
                    os.chown(path, 0, 0, follow_symlinks=False)
                    continue
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)): raise ValueError('Unexpected dependency file type')
                if stat.S_ISREG(info.st_mode) and info.st_nlink != 1: raise ValueError('Unexpected dependency hardlink')
                os.chown(path, 0, 0, follow_symlinks=False)
                path.chmod(0o755 if stat.S_ISDIR(info.st_mode) or info.st_mode & 0o111 else 0o644)

    def assets(self, app, target):
        source = target / 'frontend/dist/assets'
        if not source.exists(): return
        self.directory(app['assets'])
        for path in sorted(source.rglob('*')):
            if not path.is_file(): continue
            destination = app['assets'] / path.relative_to(source)
            for parent in reversed(destination.parent.relative_to(app['assets']).parents):
                if str(parent) != '.': self.directory(app['assets'] / parent)
            self.directory(destination.parent)
            if destination.exists():
                self.trusted(destination)
                if sha(destination) != sha(path): raise ValueError('Hashed asset collision')
            else:
                with destination.open('xb') as output: output.write(path.read_bytes())
                destination.chmod(0o644)

    def promote(self, app, target):
        temporary = app['current'].with_name('.' + app['channel'] + '-' + uuid.uuid4().hex)
        self.trusted(app['current'].parent, directory=True)
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, app['current'])


class Controller:
    def __init__(self, cfg, ops, files=None, archive=None):
        self.cfg, self.ops = cfg, ops
        self.files = files or Files(cfg)
        self.archive = archive or archive_library()

    def initialize(self):
        for root in (self.cfg.base, self.cfg.state, self.cfg.config): self.files.trusted(root, directory=True)
        for root, names in ((self.cfg.base, ['releases', 'current', 'public-assets']),
                            (self.cfg.state, ['spool', 'prepared', 'backups'])):
            for name in names: self.files.directory(root / name, 0o700 if root == self.cfg.state else 0o755)
        for channel in APPS: self.files.directory(self.cfg.app(channel)['releases'])

    def event(self, code, channel, release=''):
        path = self.cfg.state / 'events.jsonl'
        # No subprocess output, environment, path supplied by a caller, or
        # exception text is written to the audit stream.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps({'time': datetime.now(timezone.utc).isoformat(), 'event': code, 'channel': channel, 'release': release[:24]}) + '\n')

    def state(self, channel):
        path = self.cfg.state / (channel + '.json')
        return self.files.json_read(path) if path.exists() else {}

    def save(self, channel, value): self.files.json_write(self.cfg.state / (channel + '.json'), value)

    def ready(self, app, info):
        if not isinstance(info, dict) or info.get('profile') != PROFILE or info.get('channel') != app['channel'] or not re.fullmatch(r'[a-f0-9]{64}', info.get('sha256', '')):
            raise ValueError('Incompatible rollback receipt')
        name = info.get('directory', '')
        if not re.fullmatch(info['sha256'][:24] + r'-[a-f0-9]{12}', name): raise ValueError('Invalid release receipt path')
        target = app['releases'] / name
        receipt = self.files.json_read(target / '.release-ready.json')
        if receipt != info: raise ValueError('Release receipt mismatch')
        return target

    def prepare(self, app, archive):
        metadata = self.archive.verify(archive, app['channel'])
        key = app['channel'] + '-' + metadata['sha256']
        cache = self.cfg.state / 'prepared' / (key + '.json')
        if cache.exists():
            info = self.files.json_read(cache); target = self.ready(app, info)
            self.ops.preflight(app, target)
            return info
        name = metadata['sha256'][:24] + '-' + uuid.uuid4().hex[:12]
        target = app['releases'] / name
        self.files.extract(archive, target)
        self.files.link_runtime(app, target)
        self.ops.build(app, target)
        self.files.seal(app, target)
        self.ops.preflight(app, target)
        self.files.assets(app, target)
        info = {'profile': PROFILE, 'channel': app['channel'], 'directory': name, 'sha256': metadata['sha256']}
        self.files.json_write(target / '.release-ready.json', info, mode=0o644)
        self.files.json_write(cache, info)
        self.event('release_prepared', app['channel'], info['sha256'])
        return info

    def recover(self, app, value):
        pending = value.get('pending')
        if not pending: return value
        previous = pending['rollback']
        path = self.ready(app, previous)
        self.ops.preflight(app, path)
        self.ops.service(app, 'stop')
        self.files.promote(app, path)
        self.ops.service(app, 'start')
        if not self.ops.healthy(app): raise RuntimeError('Compatible rollback health failed')
        value.update(current=previous, pending=None)
        self.save(app['channel'], value)
        self.event('compatible_rollback', app['channel'], previous['sha256'])
        return value

    def activate(self, app, candidate, value):
        previous = value.get('current')
        if not previous: raise RuntimeError('A tested compatible rollback release is required')
        self.ready(app, previous); target = self.ready(app, candidate)
        if app['current'].exists() or app['current'].is_symlink():
            if not app['current'].is_symlink() or app['current'].resolve() != self.ready(app, previous):
                raise ValueError('Live pointer differs from its trusted receipt')
        self.ops.preflight(app, target)
        backup = self.cfg.state / 'backups' / (app['channel'] + '-' + uuid.uuid4().hex)
        self.files.directory(backup, 0o700)
        self.ops.backup(backup)
        value['pending'] = {'candidate': candidate, 'rollback': previous, 'backup': backup.name}
        self.save(app['channel'], value)
        try:
            self.ops.service(app, 'stop')
            self.files.promote(app, target)
            self.ops.service(app, 'start')
            if not self.ops.healthy(app): raise RuntimeError('Candidate health failed')
            value.update(current=candidate, previous=previous, pending=None, backup=backup.name)
            self.save(app['channel'], value)
            self.event('release_activated', app['channel'], candidate['sha256'])
            return {'status': 'healthy', 'channel': app['channel'], 'release': candidate['sha256'][:24]}
        except Exception:
            self.event('activation_failed', app['channel'], candidate['sha256'])
            self.recover(app, value)
            return {'status': 'rolled_back', 'channel': app['channel'], 'release': previous['sha256'][:24]}

    def deploy(self, channel, incoming):
        app = self.cfg.app(channel); stage_name(channel, incoming)
        self.ops.approved(); self.ops.unit_contract(app)
        value = self.recover(app, self.state(channel))
        source = self.files.spool(channel, incoming, self.ops.deploy_uid())
        candidate = self.prepare(app, source)
        if value.get('current', {}).get('sha256') == candidate['sha256']:
            if app['current'].resolve() != self.ready(app, candidate) or not self.ops.active(app) or not self.ops.healthy(app):
                raise RuntimeError('Current release needs operator recovery')
            return {'status': 'healthy', 'channel': channel, 'release': candidate['sha256'][:24], 'unchanged': True}
        if not value.get('current'):
            # First cutover never falls back to the pre-cookie production build.
            # Both services must already be stopped behind operator maintenance.
            if any(self.ops.active(self.cfg.app(c)) for c in APPS): raise RuntimeError('Initial cutover requires shared maintenance')
            self.files.trusted(self.cfg.config / 'maintenance')
            fallback = self.cfg.config / 'rollback' / (channel + '.tar.gz')
            self.files.trusted(fallback)
            old = self.prepare(app, fallback)
            if old['sha256'] == candidate['sha256']: raise ValueError('Initial fallback must be a separately tested artifact')
            value['current'] = old
        return self.activate(app, candidate, value)

    def rollback(self, channel):
        app = self.cfg.app(channel); self.ops.approved(); self.ops.unit_contract(app)
        value = self.recover(app, self.state(channel))
        previous = value.get('previous')
        if not previous: raise ValueError('No compatible previous release')
        self.ready(app, previous)
        return self.activate(app, previous, value)

    def status(self, channel):
        app = self.cfg.app(channel); value = self.state(channel)
        return {'channel': channel, 'active': self.ops.active(app), 'release': value.get('current', {}).get('sha256', '')[:24], 'pendingRecovery': bool(value.get('pending'))}

    def voice(self, mode, audio_hash):
        if mode not in {'enable', 'disable'} or not re.fullmatch(r'[a-f0-9]{64}', audio_hash):
            raise ValueError('Invalid voice action')
        app = self.cfg.app('admin'); value = self.state('admin')
        if value.get('pending'): raise RuntimeError('Finish pending release recovery first')
        target = self.ready(app, value.get('current'))
        self.ops.unit_contract(app)
        self.ops.voice(app, target, mode, audio_hash)
        self.event('voice_' + mode, 'admin', value['current']['sha256'])
        return {'status': 'healthy', 'channel': 'admin', 'voiceEnabled': mode == 'enable'}


def voice_contents(raw, mode):
    """Only alter the delivery switch; never silently rotate a signing key."""
    positions = {}; values = {}; lines = raw.splitlines()
    for index, line in enumerate(lines):
        text = line.strip()
        if text.startswith('#') or '=' not in text: continue
        key, value = text.split('=', 1); key = key.strip()
        if key not in {'ORDER_VOICE_ENABLED', 'ORDER_VOICE_CURSOR_SECRET'}: continue
        if key in positions: raise ValueError('Duplicate voice key')
        positions[key] = index; values[key] = value.strip().strip('"').strip("'")
    if mode == 'enable' and len(values.get('ORDER_VOICE_CURSOR_SECRET', '').encode()) < 32:
        raise ValueError('Signing key requires operator setup')
    line = 'ORDER_VOICE_ENABLED=' + ('1' if mode == 'enable' else '0')
    if 'ORDER_VOICE_ENABLED' in positions: lines[positions['ORDER_VOICE_ENABLED']] = line
    else: lines.append(line)
    return '\n'.join(lines) + '\n'


class SystemOps:
    """Only this class crosses the root/non-root execution boundary."""
    def __init__(self, cfg, files): self.cfg, self.files = cfg, files

    def _run(self, argv, *, capture=False, output=None, timeout=180):
        result = subprocess.run(argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else output if output is not None else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'},
            text=capture, timeout=timeout)
        if result.returncode: raise RuntimeError('Bounded operation failed')
        if capture and len(result.stdout) > 65536: raise ValueError('Unexpected operation output')
        return result.stdout.strip() if capture else None

    def deploy_uid(self):
        import pwd
        uid = pwd.getpwnam(self.cfg.deploy_user).pw_uid
        if uid == 0: raise ValueError('Deployment user must be non-root')
        return uid

    def principals(self):
        import pwd, grp
        names = [self.cfg.deploy_user, self.cfg.build_user, 'gingtto-maintenance', *['gingtto-' + c for c in APPS]]
        entries = [pwd.getpwnam(n) for n in names]
        if len({e.pw_uid for e in entries}) != len(names) or any(e.pw_uid == 0 for e in entries):
            raise ValueError('Runtime, build and deployment identities must be distinct')
        primary_groups = [grp.getgrnam(n).gr_gid for n in names]
        if len(set(primary_groups)) != len(names) or any(e.pw_gid != gid for e, gid in zip(entries, primary_groups)):
            raise ValueError('Each service identity must have a dedicated primary group')
        runtime_groups = {c: grp.getgrnam('gingtto-' + c).gr_gid for c in APPS}
        if len(set(runtime_groups.values())) != 2 or 0 in runtime_groups.values(): raise ValueError('Runtime secret groups must be separate')
        for channel, gid in runtime_groups.items():
            if pwd.getpwnam('gingtto-' + channel).pw_gid != gid: raise ValueError('Runtime primary group must be dedicated')
        for entry in entries:
            groups = set(os.getgrouplist(entry.pw_name, entry.pw_gid))
            privileged = {0}
            for name in ('sudo', 'admin', 'docker'):
                try: privileged.add(grp.getgrnam(name).gr_gid)
                except KeyError: pass
            if groups & privileged: raise ValueError('Privileged runtime/deployment group membership')
            for channel, gid in runtime_groups.items():
                if entry.pw_name != 'gingtto-' + channel and gid in groups:
                    raise ValueError('Cross-role access to runtime configuration')

    def approved(self):
        value = self.files.json_read(self.cfg.config / 'security-cutover-approved')
        now = datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(value.get('expiresAt', ''))
        if value.get('profile') != PROFILE or value.get('maintenanceAcknowledged') is not True or value.get('productionChangesApproved') is not True or not 0 < (expiry - now).total_seconds() <= 86400:
            raise PermissionError('Current operator cutover approval required')

    def _transient(self, app, target, argv, *, build=False, writable=()):
        user = self.cfg.build_user if build else app['user']
        group = self.cfg.build_user if build else app['group']
        properties = ['User=' + user, 'Group=' + group, 'WorkingDirectory=' + str(target / app['backend']),
            'NoNewPrivileges=yes', 'ProtectSystem=strict', 'ProtectHome=yes', 'PrivateTmp=yes',
            'KillMode=control-group', 'RuntimeMaxSec=600' if build else 'RuntimeMaxSec=120',
            'TimeoutStopSec=10', 'MemoryMax=1G', 'TasksMax=128', 'UMask=0027',
            'Environment=PYTHONDONTWRITEBYTECODE=1 PIP_CONFIG_FILE=/dev/null', 'StandardOutput=null', 'StandardError=null']
        if writable: properties.append('ReadWritePaths=' + ' '.join(str(p) for p in writable))
        command = ['/usr/bin/systemd-run', '--quiet', '--wait', '--collect', '--service-type=exec',
                   '--unit=gingtto-release-' + uuid.uuid4().hex]
        for value in properties: command += ['--property=' + value]
        self._run(command + ['--', *map(str, argv)], timeout=650 if build else 150)

    def build(self, app, target):
        import pwd
        builder = pwd.getpwnam(self.cfg.build_user)
        venv = target / app['backend'] / '.venv'
        venv.mkdir(mode=0o755); os.chown(venv, builder.pw_uid, builder.pw_gid)
        self._transient(app, target, ['/usr/bin/python3', '-m', 'venv', venv], build=True, writable=[venv])
        self._transient(app, target, [venv / 'bin/python', '-m', 'pip', 'install', '--no-input', '--disable-pip-version-check', '--no-cache-dir', '-r', target / app['backend'] / 'requirements.txt'], build=True, writable=[venv])

    def preflight(self, app, target):
        self._transient(app, target, ['/usr/bin/python3', '-I', '-c', storage_probe(app, target)],
                        writable=[app['primary'] / 'data', app['primary'] / 'uploads'])
        self._transient(app, target, [target / app['backend'] / '.venv/bin/python', target / 'scripts/verify-security.py', app['backend'], '--production-ready', '--profile', 'phase1'])
        self._transient(app, target, [target / app['backend'] / '.venv/bin/python', '-c', 'import app'])

    def unit_contract(self, app):
        import grp
        self.files.trusted(app['primary'], directory=True)
        for old in app['primary'].glob('.env*'):
            if old.name == '.env.example': continue
            info = self.files.trusted(old)
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise PermissionError('Legacy owner credentials must be root-only')
        expected = {'User': app['user'], 'Group': app['group'], 'WorkingDirectory': str(app['current'] / app['backend']), 'NoNewPrivileges': 'yes', 'ProtectSystem': 'strict'}
        for key, value in expected.items():
            actual = self._run(['/usr/bin/systemctl', 'show', '--property=' + key, '--value', app['service']], capture=True)
            if actual != value: raise ValueError('Service hardening contract mismatch')
        paths = self._run(['/usr/bin/systemctl', 'show', '--property=ReadWritePaths', '--value', app['service']], capture=True)
        required_paths = {str(app['primary'] / 'data'), str(app['primary'] / 'uploads'), str(self.cfg.base / 'private-files' / app['channel'])}
        if set(shlex.split(paths)) != required_paths:
            raise ValueError('Service writable paths must be explicitly bounded')
        executable = str(app['current'] / app['backend'] / '.venv/bin/gunicorn')
        command = self._run(['/usr/bin/systemctl', 'show', '--property=ExecStart', '--value', app['service']], capture=True)
        if not re.search(r'path=' + re.escape(executable) + r'\s*;', command) or not re.search(r'argv\[\]=' + re.escape(executable + ' --config gunicorn.conf.py app:app') + r'\s*;', command):
            raise ValueError('Service executable differs from immutable release')
        environment = self._run(['/usr/bin/systemctl', 'show', '--property=EnvironmentFiles', '--value', app['service']], capture=True)
        if re.findall(r'(/[^\s()]+)', environment) != [str(app['env']), str(app['security_env'])] or 'ignore_errors=yes' in environment:
            raise ValueError('Service must use only its dedicated runtime configuration')
        direct = self._run(['/usr/bin/systemctl', 'show', '--property=Environment', '--value', app['service']], capture=True)
        if set(shlex.split(direct)) != {'PYTHONDONTWRITEBYTECODE=1'}:
            raise ValueError('Service has unmanaged environment overrides')
        for key in ('PassEnvironment', 'UnsetEnvironment'):
            if self._run(['/usr/bin/systemctl', 'show', '--property=' + key, '--value', app['service']], capture=True):
                raise ValueError('Service environment inheritance/removal is not supported')
        for path in (app['env'], app['security_env']):
            info = self.files.trusted(path)
            if info.st_gid != grp.getgrnam(app['group']).gr_gid or stat.S_IMODE(info.st_mode) != 0o640:
                raise PermissionError('Runtime secret file ownership/mode')
        # Configuration is never emitted or passed on command lines. The app's
        # real read-only preflight validates host lists, secret and DB identity.
        values = runtime_values(app['env'].read_text(encoding='utf-8'), app['security_env'].read_text(encoding='utf-8'),
                                self.cfg.database, app['channel'])
        for channel in APPS:
            key = 'SECURITY_' + channel.upper() + '_LEGACY_UPLOADS'
            expected_path = str(self.cfg.app(channel)['primary'] / 'uploads')
            if values.get(key, expected_path) != expected_path:
                raise ValueError('Legacy storage must match the prepared persistent directory')

    def loaded_voice(self, app, mode):
        """Verify the restarted master received the switch, without a login.

        Inspect only this fixed service's process environment; no values are
        printed or returned. Comparing only files misses shadowed/stale config.
        """
        def main_pid():
            value = self._run(['/usr/bin/systemctl', 'show', '--property=MainPID', '--value', app['service']], capture=True)
            if not re.fullmatch(r'[1-9][0-9]*', value) or int(value) <= 1:
                raise RuntimeError('Notification service master is not running')
            return int(value)
        pid = main_pid()
        descriptor = os.open('/proc/' + str(pid) + '/environ', os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as source: raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or main_pid() != pid:
            raise RuntimeError('Notification service changed during verification')
        environment = {}
        for item in raw.split(b'\0'):
            if b'=' not in item: continue
            key, value = item.split(b'=', 1)
            if key in {b'ORDER_VOICE_ENABLED', b'ORDER_VOICE_CURSOR_SECRET'}:
                if key in environment: raise RuntimeError('Ambiguous loaded notification configuration')
                environment[key] = value
        expected = env_values(app['env'].read_text(encoding='utf-8'))
        if environment.get(b'ORDER_VOICE_ENABLED') != (b'1' if mode == 'enable' else b'0') or not hmac.compare_digest(
                environment.get(b'ORDER_VOICE_CURSOR_SECRET', b''), expected['ORDER_VOICE_CURSOR_SECRET'].encode()):
            raise RuntimeError('Loaded notification configuration does not match')

    def service(self, app, action):
        if action not in {'start', 'stop', 'restart'}: raise ValueError('Invalid service action')
        self._run(['/usr/bin/systemctl', action, app['service']], timeout=180)

    def active(self, app):
        result = subprocess.run(['/usr/bin/systemctl', 'is-active', '--quiet', app['service']],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin'}, timeout=15)
        return result.returncode == 0

    def healthy(self, app):
        opener = build_opener(ProxyHandler({}))
        for _ in range(25):
            try:
                with opener.open('http://127.0.0.1:' + str(app['port']) + '/api/health', timeout=3) as response:
                    if response.status == 200 and json.loads(response.read(4096)).get('status') == 'ok': return True
            except Exception: pass
            time.sleep(1)
        return False

    def backup(self, directory):
        # Fixed local peer-authenticated command and explicit read-only session;
        # no caller-supplied SQL, restore, migration or database name is accepted.
        environment = ['/usr/bin/env', 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=120000']
        command = ['/usr/sbin/runuser', '-u', 'postgres', '--', *environment]
        with (directory / 'database.dump').open('xb') as stream:
            self._run(command + ['/usr/bin/pg_dump', '-Fc', '--no-password', '--dbname=' + self.cfg.database], output=stream, timeout=180)
        (directory / 'database.dump').chmod(0o600)
        self._run(['/usr/bin/pg_restore', '--list', '--file=/dev/null', directory / 'database.dump'])
        sql = "SELECT json_build_object('orders',(SELECT count(*) FROM orders),'products',(SELECT count(*) FROM products),'sizes',(SELECT count(*) FROM product_size_prices),'inventory',(SELECT md5(string_agg(id::text||':'||stock::text,',' ORDER BY id)) FROM product_size_prices));"
        value = self._run(command + ['/usr/bin/psql', '-X', '--no-password', '-d', self.cfg.database, '-At', '-v', 'ON_ERROR_STOP=1', '-c', sql], capture=True)
        self.files.json_write(directory / 'business-summary.json', json.loads(value))
        for channel in APPS:
            app = self.cfg.app(channel)
            with (directory / (channel + '-files.tar.gz')).open('xb') as stream:
                self._run(['/usr/sbin/runuser', '-u', app['user'], '--', '/usr/bin/tar', '--one-file-system', '--exclude=data/image-cache', '--exclude=*.lock', '-czf', '-', '-C', app['primary'], 'data', 'uploads'], output=stream, timeout=180)
            (directory / (channel + '-files.tar.gz')).chmod(0o600)
            for name, path in [('env', app['env']), ('security.env', app['security_env'])]:
                with (directory / (channel + '.' + name)).open('xb') as stream: stream.write(path.read_bytes())
                (directory / (channel + '.' + name)).chmod(0o600)

    def _replace_env(self, path, raw):
        info = self.files.trusted(path)
        temporary = path.with_name('.voice-' + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        try:
            with os.fdopen(fd, 'wb') as output: output.write(raw); output.flush(); os.fsync(output.fileno())
            os.chown(temporary, info.st_uid, info.st_gid); temporary.chmod(0o640)
            os.replace(temporary, path)
        finally: temporary.unlink(missing_ok=True)

    def voice(self, app, target, mode, audio_hash):
        matching = [p for p in (target / 'frontend/dist/assets').glob('new-order-zh-CN-*.wav') if sha(p) == audio_hash]
        if mode == 'enable' and not matching: raise ValueError('Release audio mismatch')
        old = app['env'].read_bytes()
        updated = voice_contents(old.decode('utf-8'), mode).encode()
        backup = self.cfg.state / 'backups' / ('voice-' + uuid.uuid4().hex)
        self.files.directory(backup, 0o700)
        with (backup / 'admin.env').open('xb') as output: output.write(old)
        (backup / 'admin.env').chmod(0o600)
        self._replace_env(app['env'], updated)
        try:
            self.service(app, 'restart')
            if not self.healthy(app): raise RuntimeError('Voice restart health failed')
            self.loaded_voice(app, mode)
            self._transient(app, target, [target / app['backend'] / '.venv/bin/python', target / 'scripts/verify-order-notifications.py', '--http', '--expect-enabled', mode, '--audio-sha256', audio_hash])
        except Exception:
            self._replace_env(app['env'], old)
            self.service(app, 'restart')
            if not self.healthy(app): raise RuntimeError('Voice rollback health failed')
            self.loaded_voice(app, 'enable' if env_values(old.decode())['ORDER_VOICE_ENABLED'] == '1' else 'disable')
            raise


def main(argv=None):
    import argparse
    class Parser(argparse.ArgumentParser):
        def error(self, message): raise ValueError('Invalid bounded operation arguments')
    parser = Parser()
    sub = parser.add_subparsers(dest='action', required=True)
    deploy = sub.add_parser('deploy'); deploy.add_argument('channel', choices=APPS); deploy.add_argument('incoming')
    for action in ('status', 'rollback'):
        command = sub.add_parser(action); command.add_argument('channel', choices=APPS)
    voice = sub.add_parser('voice'); voice.add_argument('mode', choices=['enable', 'disable']); voice.add_argument('audio_hash')
    args = parser.parse_args(argv)
    if os.name != 'posix' or os.geteuid() != 0: raise PermissionError('Root-installed bounded controller required')
    os.umask(0o077)
    import signal
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    cfg = Config(); files = Files(cfg)
    # Validate the installed program/library and every writable controller root.
    for path in (Path(__file__), Path(__file__).with_name('build_release.py')): files.trusted(path)
    for path in (Path(__file__).parent, cfg.base, cfg.config, cfg.state): files.trusted(path, directory=True)
    ops = SystemOps(cfg, files); ops.principals()
    controller = Controller(cfg, ops, files); controller.initialize()
    import fcntl
    fd = os.open(cfg.state / 'controller.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == 'deploy': result = controller.deploy(args.channel, args.incoming)
        elif args.action == 'rollback': result = controller.rollback(args.channel)
        elif args.action == 'voice': result = controller.voice(args.mode, args.audio_hash)
        else: result = controller.status(args.channel)
    print(json.dumps(result))
    return 1 if result.get('status') == 'rolled_back' else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # stdout/stderr never contain environment, SQL rows or subprocess output.
        print(json.dumps({'status': 'operation_failed', 'errorType': type(exc).__name__}))
        raise SystemExit(2)
