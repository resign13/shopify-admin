"""Real POSIX fixture. Run explicitly inside a --network none test container.

Uses real Linux UIDs, file modes, fd-relative intake and atomic symlink switches.
It substitutes only the unavailable systemd manager and database backup in the
container; actual application/DB/voice regressions are separate acceptance tests.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import hashlib
import subprocess
import sys
from unittest.mock import patch

from build_release import build, required, verify
from release_control import Config, Controller, Files, SystemOps, PROFILE, env_values, storage_probe
if os.name == 'posix':
    import grp
    import pwd


class LinuxFixtureOps(SystemOps):
    def __init__(self, cfg, files):
        super().__init__(cfg, files)
        self.services = {}; self.health_fail = False; self.backups = 0
        self.voice_check_fails = False

    def _transient(self, app, target, argv, **kwargs):
        if not any(str(p).endswith('verify-order-notifications.py') for p in argv): raise AssertionError('Unexpected fixture transient call')
        if self.voice_check_fails: raise RuntimeError('Synthetic post-toggle check failure')
        expected = argv[argv.index('--expect-enabled') + 1] == 'enable'
        code = f"import sys;sys.path.insert(0,{str(target / app['backend'])!r});import db,order_notifications;assert order_notifications.enabled() == {expected!r}"
        self.user(app['user'], code)

    def loaded_voice(self, app, mode):
        # A real non-root child receives canonical EnvironmentFile values. Only
        # systemd's PID lookup is substituted, not /proc or the verifier itself.
        environment = {'PATH': '/usr/bin:/bin', **env_values(app['env'].read_text()),
                       **env_values(app['security_env'].read_text())}
        with subprocess.Popen(['/usr/sbin/runuser', '-u', app['user'], '--', sys.executable, '-u', '-c',
                'import os,time;print(os.getpid(),flush=True);time.sleep(30)'], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as process:
            pid = process.stdout.readline().strip()
            try:
                with patch.object(self, '_run', return_value=pid):
                    SystemOps.loaded_voice(self, app, mode)
                    try: SystemOps.loaded_voice(self, app, 'disable' if mode == 'enable' else 'enable')
                    except RuntimeError: pass
                    else: raise AssertionError('Stale loaded voice switch accepted')
            finally:
                os.kill(int(pid), 15)
                process.wait(timeout=10)

    def user(self, name, code):
        result = subprocess.run(['/usr/sbin/runuser', '-u', name, '--', sys.executable, '-c', code],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        if result.returncode: raise AssertionError('Non-root fixture probe failed: ' + result.stderr)
        return result.stdout.strip()

    def build(self, app, target):
        builder = pwd.getpwnam(self.cfg.build_user)
        venv = target / app['backend'] / '.venv'; venv.mkdir()
        os.chown(venv, builder.pw_uid, builder.pw_gid)
        code = f'''from pathlib import Path
import os
root=Path({str(venv)!r})
(root/'bin').mkdir()
(root/'bin/python').write_text('synthetic interpreter marker')
(root/'build-uid').write_text(str(os.getuid()))
try: open({str(app['env'])!r}).read()
except PermissionError: pass
else: raise AssertionError('Builder read runtime credentials')
'''
        if 'UNSAFE-BUILD' in (target / app['backend'] / 'app.py').read_text():
            code += f"(root/'escape').symlink_to('/etc/passwd')\n"
        self.user(self.cfg.build_user, code)
        assert int((venv / 'build-uid').read_text()) == builder.pw_uid != 0

    def preflight(self, app, target):
        self.user(app['user'], storage_probe(app, target))
        other = self.cfg.app('store' if app['channel'] == 'admin' else 'admin')
        expected = pwd.getpwnam(app['user']).pw_uid
        code = f'''from pathlib import Path
import os,runpy
assert os.getuid()=={expected} and os.getuid()!=0
assert 'FIXTURE_SECRET' in Path({str(app['env'])!r}).read_text()
for protected in [{str(other['security_env'])!r},{str(app['primary']/'.env')!r}]:
    try: Path(protected).read_text()
    except PermissionError: pass
    else: raise AssertionError('Runtime read another identity credential')
try: Path({str(target/app['backend']/'app.py')!r}).write_text('not allowed')
except PermissionError: pass
else: raise AssertionError('Runtime modified immutable code')
runpy.run_path({str(target/app['backend']/'app.py')!r})
print(os.getuid())
'''
        assert int(self.user(app['user'], code)) == expected

    def unit_contract(self, app):
        # There is no systemd PID 1 in this fixture. Do not claim this exercises
        # a live service unit; argv/hardening contract has dedicated unit tests.
        for path in (app['env'], app['security_env']):
            info = self.files.trusted(path)
            assert info.st_gid == grp.getgrnam(app['group']).gr_gid
            assert info.st_mode & 0o777 == 0o640

    def active(self, app): return self.services.get(app['channel'], False)
    def service(self, app, action): self.services[app['channel']] = action != 'stop'
    def healthy(self, app):
        target = app['current'].resolve()
        return 'FAIL-HEALTH' not in (target / app['backend'] / 'app.py').read_text()

    def backup(self, directory):
        self.backups += 1
        (directory / 'database.dump').write_bytes(b'isolated synthetic database backup')
        (directory / 'database.dump').chmod(0o600)


def package(cfg, name, marker):
    root = cfg.state / 'source' / name; root.mkdir(parents=True)
    for relative in required('admin'):
        path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('MARKER = ' + repr(marker) + '\n' if relative.endswith('/app.py') else 'synthetic source\n')
    # Exercise the real loader precedence in the non-root transient probe.
    (root / 'admin-backend/db.py').write_text('''import os
from pathlib import Path
for name in ['.env.security','.env']:
    for line in (Path(__file__).parent/name).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key,value=line.split('=',1);os.environ.setdefault(key,value)
''')
    (root / 'admin-backend/order_notifications.py').write_text("import os\ndef enabled(): return os.environ.get('ORDER_VOICE_ENABLED') == '1'\n")
    (root / 'frontend/dist/assets').mkdir()
    (root / 'frontend/dist/assets' / (name + '.js')).write_text('const synthetic=true;')
    (root / 'frontend/dist/assets/new-order-zh-CN-abcdef.wav').write_bytes(b'fixture-wave-not-a-production-recording')
    target = cfg.state / (name + '.tar.gz'); build(root, target, 'admin'); target.chmod(0o600)
    return target


def incoming(cfg, number, archive):
    deploy = pwd.getpwnam(cfg.deploy_user)
    name = 'admin-' + str(number) + '-1'
    stage = cfg.base / 'incoming' / name; stage.mkdir(mode=0o700)
    os.chown(stage, deploy.pw_uid, deploy.pw_gid)
    target = stage / 'release.tar.gz'; shutil.copyfile(archive, target)
    target.chmod(0o600); os.chown(target, deploy.pw_uid, deploy.pw_gid)
    return name


def main():
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/.dockerenv').is_file() or os.environ.get('SECURITY_RELEASE_FIXTURE') != '1' or {p.name for p in Path('/sys/class/net').iterdir()} != {'lo'}:
        raise RuntimeError('Explicit isolated network-none Linux fixture required')
    cfg = Config()
    for user in [cfg.deploy_user, cfg.build_user, 'gingtto-maintenance', 'gingtto-admin', 'gingtto-store']:
        subprocess.run(['/usr/sbin/useradd', '-r', '-U', '-M', '-s', '/usr/sbin/nologin', user], check=True)
    for path in [cfg.base, cfg.state, cfg.config]: path.mkdir(parents=True); path.chmod(0o755)
    deploy = pwd.getpwnam(cfg.deploy_user)
    intake = cfg.base / 'incoming'; intake.mkdir(mode=0o700); os.chown(intake, deploy.pw_uid, deploy.pw_gid)
    (cfg.config / 'runtime').mkdir(); (cfg.config / 'rollback').mkdir()
    for channel in ['admin', 'store']:
        app = cfg.app(channel); account = pwd.getpwnam(app['user'])
        app['primary'].mkdir(parents=True)
        for name in ['data', 'uploads']:
            path = app['primary'] / name; path.mkdir(); os.chown(path, account.pw_uid, account.pw_gid)
        old = app['primary'] / '.env'; old.write_text('OLD_OWNER_CREDENTIAL=synthetic\n'); old.chmod(0o600)
        for path, raw in [(app['env'], 'FIXTURE_SECRET=synthetic-not-real\nORDER_VOICE_ENABLED=0\nORDER_VOICE_CURSOR_SECRET=fixture-signing-key-not-for-production-2026\n'),
                (app['security_env'], 'APP_ENV=production\nDB_SCHEMA_AUTO_MIGRATE=0\nSECURITY_ATTACHMENT_MODE=legacy\nSECURITY_LOGIN_PROTECTION_ENABLED=0\nPGDATABASE=smawell_admin\nPGHOST=127.0.0.1\n')]:
            path.write_text(raw)
            os.chown(path, 0, account.pw_gid); path.chmod(0o640)
    fs = Files(cfg); ops = LinuxFixtureOps(cfg, fs)
    ops.principals()
    for user in [cfg.deploy_user, cfg.build_user, 'gingtto-maintenance']:
        protected = [str(cfg.app(channel)[key]) for channel in ['admin', 'store'] for key in ['env', 'security_env']]
        ops.user(user, f'''from pathlib import Path
for name in {protected!r}:
    try: Path(name).read_bytes()
    except PermissionError: pass
    else: raise AssertionError('Auxiliary identity read runtime secrets')
''')
    # Exercise real unit-contract parsing and secret modes; only the absent
    # manager's serialized property responses are substituted.
    contract = SystemOps(cfg, fs); app = cfg.app('admin')
    executable = str(app['current'] / app['backend'] / '.venv/bin/gunicorn')
    properties = {'User': app['user'], 'Group': app['group'], 'WorkingDirectory': str(app['current'] / app['backend']), 'NoNewPrivileges': 'yes', 'ProtectSystem': 'strict',
        'ReadWritePaths': ' '.join(str(p) for p in [app['primary']/'data',app['primary']/'uploads',cfg.base/'private-files'/app['channel']]),
        'ExecStart': '{ path=' + executable + ' ; argv[]=' + executable + ' --config gunicorn.conf.py app:app ; ignore_errors=no ; }',
        'EnvironmentFiles': str(app['env']) + ' (ignore_errors=no) ' + str(app['security_env']) + ' (ignore_errors=no)',
        'Environment': 'PYTHONDONTWRITEBYTECODE=1', 'PassEnvironment': '', 'UnsetEnvironment': ''}
    def property_value(argv, **kwargs):
        key=next(value.split('=',1)[1] for value in argv if value.startswith('--property='))
        return properties[key]
    with patch.object(contract, '_run', side_effect=property_value):
        contract.unit_contract(app)
        for key, bad in [('User','root'),('ExecStart','{ path=/bin/sh ; argv[]=/bin/sh ; }'),('EnvironmentFiles',properties['EnvironmentFiles']+' /old/owner.env (ignore_errors=no)'),
                ('Environment','PYTHONDONTWRITEBYTECODE=1 GUNICORN_CMD_ARGS=bad'), ('PassEnvironment','PGPASSWORD'), ('UnsetEnvironment','ORDER_VOICE_ENABLED'), ('ReadWritePaths','/')]:
            old=properties[key];properties[key]=bad
            try:contract.unit_contract(app)
            except ValueError:pass
            else:raise AssertionError('Invalid unit contract accepted')
            properties[key]=old
        (app['primary']/'.env').chmod(0o640)
        try:contract.unit_contract(app)
        except PermissionError:pass
        else:raise AssertionError('Readable legacy owner credential accepted')
        (app['primary']/'.env').chmod(0o600)
        raw = app['security_env'].read_text()
        app['security_env'].write_text(raw + 'ORDER_VOICE_ENABLED=1\n')
        try: contract.unit_contract(app)
        except ValueError: pass
        else: raise AssertionError('Shadowed voice configuration accepted')
        app['security_env'].write_text(raw)
    fs.json_write(cfg.config / 'security-cutover-approved', {'profile': PROFILE, 'maintenanceAcknowledged': True, 'productionChangesApproved': True, 'expiresAt': (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()})
    (cfg.config / 'maintenance').write_text('synthetic maintenance')
    control = Controller(cfg, ops, fs); control.initialize()
    old = package(cfg, 'old', 'GOOD-OLD')
    new = package(cfg, 'new', 'GOOD-NEW')
    shutil.copyfile(old, cfg.config / 'rollback/admin.tar.gz')
    (cfg.config / 'rollback/admin.tar.gz').chmod(0o600)
    result = control.deploy('admin', incoming(cfg, 1, new))
    assert result['status'] == 'healthy'
    old_pointer = cfg.app('admin')['current'].resolve()
    # Read-only permissions probing must detect the root-owned lock files that
    # an old root service can leave behind, without rewriting/removing them.
    app = cfg.app('admin'); cache = app['primary'] / 'data/image-cache'
    cache.mkdir(); os.chown(cache, pwd.getpwnam(app['user']).pw_uid, grp.getgrnam(app['group']).gr_gid)
    lock = cache / 'stripe-1.lock'; lock.write_bytes(b'fixture-lock'); lock.chmod(0o600)
    try: ops.preflight(app, old_pointer)
    except AssertionError: pass
    else: raise AssertionError('Unreadable root-owned cache lock was accepted')
    assert lock.read_bytes() == b'fixture-lock' and lock.stat().st_uid == 0
    lock.unlink()
    data = app['primary'] / 'data'; mode = data.stat().st_mode & 0o777; data.chmod(0o500)
    try: ops.preflight(app, old_pointer)
    except AssertionError: pass
    else: raise AssertionError('Unwritable runtime data directory was accepted')
    finally: data.chmod(mode)
    failed = package(cfg, 'failed', 'FAIL-HEALTH')
    assert control.deploy('admin', incoming(cfg, 2, failed))['status'] == 'rolled_back'
    assert cfg.app('admin')['current'].resolve() == old_pointer
    assert control.rollback('admin')['status'] == 'healthy'
    assert 'GOOD-OLD' in (cfg.app('admin')['current'] / 'admin-backend/app.py').read_text()
    app = cfg.app('admin'); original = app['env'].read_bytes()
    audio_hash = hashlib.sha256(b'fixture-wave-not-a-production-recording').hexdigest()
    assert control.voice('enable', audio_hash)['voiceEnabled'] is True
    enabled = app['env'].read_bytes()
    assert b'ORDER_VOICE_ENABLED=1' in enabled and b'fixture-signing-key-not-for-production-2026' in enabled
    assert app['env'].stat().st_mode & 0o777 == 0o640
    assert app['env'].stat().st_gid == grp.getgrnam(app['group']).gr_gid
    ops.voice_check_fails = True
    try: control.voice('disable', audio_hash)
    except RuntimeError: pass
    else: raise AssertionError('Voice check failure was not reported')
    assert app['env'].read_bytes() == enabled
    ops.voice_check_fails = False
    assert control.voice('disable', audio_hash)['voiceEnabled'] is False
    assert app['env'].read_bytes() == original
    # Unsafe dependency symlinks never reach live code or modify system files.
    before = Path('/etc/passwd').read_bytes()
    unsafe = package(cfg, 'unsafe', 'UNSAFE-BUILD')
    try: control.deploy('admin', incoming(cfg, 3, unsafe))
    except ValueError: pass
    else: raise AssertionError('Unsafe build symlink was accepted')
    assert Path('/etc/passwd').read_bytes() == before
    # Intake cannot traverse a symlink directory, symlink file or hardlink.
    (intake / 'admin-90-1').symlink_to('/etc', target_is_directory=True)
    symlink_dir = intake / 'admin-91-1'; symlink_dir.mkdir(mode=0o700); os.chown(symlink_dir, deploy.pw_uid, deploy.pw_gid)
    (symlink_dir / 'release.tar.gz').symlink_to(new)
    hard = incoming(cfg, 92, new)
    other = intake / 'admin-93-1'; other.mkdir(mode=0o700); os.chown(other, deploy.pw_uid, deploy.pw_gid)
    os.link(intake / hard / 'release.tar.gz', other / 'release.tar.gz')
    for name in ['admin-90-1', 'admin-91-1', hard, 'admin-93-1']:
        try: fs.spool('admin', name, deploy.pw_uid)
        except (OSError, ValueError): pass
        else: raise AssertionError('Unsafe intake was accepted')
    name = incoming(cfg, 94, new)
    sealed = fs.spool('admin', name, deploy.pw_uid)
    (intake / name / 'release.tar.gz').write_bytes(b'changed after intake')
    assert verify(sealed, 'admin')['dataFree']
    assert (cfg.app('admin')['assets'] / 'old.js').is_file() and (cfg.app('admin')['assets'] / 'new.js').is_file()
    print(json.dumps({'realLinuxUids': True, 'runtimeSecretIsolation': True, 'builderHasNoRuntimeSecrets': True,
        'immutableCode': True, 'atomicPointerSwitch': True, 'failedHealthRollback': True,
        'explicitCompatibleRollback': True, 'databaseNeverRestored': True, 'stageFdAndLinkGuards': True,
        'sealedArchiveRaceGuard': True, 'unsafeDependencySymlinkRejected': True, 'retainedHashedAssets': True,
        'voiceConfigurationRollback': True, 'voiceSecretPermissionsPreserved': True, 'unitContractAndLegacyOwnerSecrets': True,
        'loadedNonRootVoiceSwitchVerified': True, 'shadowedConfigurationRejected': True,
        'maintenanceHasNoRuntimeSecrets': True,
        'metadataOnlyPersistentPermissionGate': True, 'oldRootCacheLockRejected': True,
        'systemdManager': 'substituted; command contract tested separately', 'productionModified': False}))


if __name__ == '__main__': main()
