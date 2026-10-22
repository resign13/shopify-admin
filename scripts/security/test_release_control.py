"""State-machine tests. Linux ownership/UID checks have a separate real fixture."""
from pathlib import Path
import os
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from build_release import build, required
from release_control import Config, Controller, Files, PROFILE, SystemOps, stage_name, voice_contents, runtime_values, env_values


class FixtureFiles(Files):
    def trusted(self, path, *, directory=False):
        path = Path(path)
        if not path.exists(): raise FileNotFoundError('Missing fixture controller path')
        if path.is_symlink() or path.is_dir() != directory:
            raise ValueError('Invalid fixture controller path')
        return path.stat()

    def spool(self, channel, incoming, deploy_uid):
        stage_name(channel, incoming)
        target = self.cfg.state / 'spool' / (incoming + '.tar.gz')
        shutil.copyfile(self.cfg.base / 'incoming' / incoming / 'release.tar.gz', target)
        return target

    def seal(self, app, target):
        pass  # Do not claim Windows tests prove POSIX ownership or immutability.

    def promote(self, app, target):
        # Win32 cannot replace an existing directory symlink using rename(2).
        # This adapter tests state transitions only; Linux exercises the actual
        # atomic implementation without this adapter.
        if os.name == 'nt' and app['current'].is_symlink(): app['current'].unlink()
        return super().promote(app, target)


class FixtureOps:
    def __init__(self): self.calls = []; self.health = []; self.running = False
    def static_ready(self, app, target): return self.running
    def approved(self): self.calls.append('approval')
    def unit_contract(self, app): self.calls.append('unit_contract')
    def deploy_uid(self): return 9999
    def active(self, app): return self.running
    def build(self, app, target):
        self.calls.append('non_root_build')
        (target / app['backend'] / '.venv').mkdir()
    def preflight(self, app, target):
        self.calls.append('non_root_preflight')
        if 'reject-preflight' in (target / app['backend'] / 'app.py').read_text(): raise ValueError('Synthetic preflight failure')
    def backup(self, directory):
        self.calls.append('readonly_backup')
        (directory / 'database.dump').write_bytes(b'synthetic database backup')
    def service(self, app, action):
        self.calls.append(action); self.running = action != 'stop'
    def healthy(self, app): return self.health.pop(0) if self.health else True
    def voice(self, app, target, mode, audio_hash): self.calls.append('voice_' + mode)


class FixtureController(Controller):
    def event(self, code, channel, release=''): self.ops.calls.append('event:' + code)


class ReleaseControlTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cfg = Config(base=root / 'base', state=root / 'state', config=root / 'config')
        for p in [self.cfg.base, self.cfg.state, self.cfg.config]: p.mkdir()
        self.ops = FixtureOps(); self.files = FixtureFiles(self.cfg)
        self.control = FixtureController(self.cfg, self.ops, self.files)
        self.control.initialize()
        for channel in ['admin', 'store']:
            app = self.cfg.app(channel)
            for name in ['data', 'uploads']: (app['primary'] / name).mkdir(parents=True)
            app['env'].parent.mkdir(parents=True, exist_ok=True)
            app['env'].write_text('fixture runtime\n'); app['security_env'].write_text('fixture security\n')
        self.old = self.package('old')
        app = self.cfg.app('admin')
        info = self.control.prepare(app, self.old)
        self.files.promote(app, self.control.ready(app, info))
        self.control.save('admin', {'current': info, 'previous': None, 'pending': None})
        self.ops.calls.clear()

    def package(self, name, body=None):
        root = Path(self.temp.name) / ('source-' + name); root.mkdir()
        for relative in required('admin'):
            path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body if body and relative.endswith('/app.py') else name)
        (root / 'frontend/dist/assets').mkdir()
        (root / 'frontend/dist/assets' / (name + '.js')).write_text('const fixture = true;')
        archive = Path(self.temp.name) / (name + '.tar.gz'); build(root, archive, 'admin')
        return archive

    def incoming(self, archive, name='admin-1-1'):
        stage = self.cfg.base / 'incoming' / name; stage.mkdir(parents=True)
        shutil.copyfile(archive, stage / 'release.tar.gz')
        return name

    def test_frontend_only_release_and_recovery_do_not_restart(self):
        source = Path(self.temp.name) / 'source-static'
        shutil.copytree(Path(self.temp.name) / 'source-old',source)
        (source/'frontend/dist/index.html').write_text('static only')
        archive=Path(self.temp.name)/'static.tar.gz';build(source,archive,'admin')
        self.ops.running=True
        result=self.control.deploy('admin',self.incoming(archive))
        self.assertTrue(result['staticOnly'])
        self.assertNotIn('stop',self.ops.calls)
        self.assertNotIn('start',self.ops.calls)
        self.ops.calls.clear();self.ops.health=[False,True]
        result=self.control.rollback('admin')
        self.assertEqual(result['status'],'rolled_back')
        self.assertNotIn('stop',self.ops.calls)
        self.assertNotIn('start',self.ops.calls)

    def test_frontend_only_release_requires_matching_loaded_runtime(self):
        source=Path(self.temp.name)/'source-static'
        shutil.copytree(Path(self.temp.name)/'source-old',source)
        (source/'frontend/dist/index.html').write_text('static only')
        archive=Path(self.temp.name)/'static.tar.gz';build(source,archive,'admin')
        self.ops.running=False
        result=self.control.deploy('admin',self.incoming(archive))
        self.assertFalse(result['staticOnly'])
        self.assertIn('stop',self.ops.calls)
        self.assertIn('start',self.ops.calls)

    def test_successful_release_retains_previous_code_and_assets_not_database_restore(self):
        archive = self.package('new')
        old = self.control.state('admin')['current']
        result = self.control.deploy('admin', self.incoming(archive))
        self.assertEqual(result['status'], 'healthy')
        current = self.control.state('admin')
        self.assertEqual(current['previous'], old)
        self.assertIsNone(current['pending'])
        app = self.cfg.app('admin')
        self.assertEqual(app['current'].resolve(), self.control.ready(app, current['current']))
        self.assertTrue((app['assets'] / 'old.js').is_file())
        self.assertTrue((app['assets'] / 'new.js').is_file())
        self.assertLess(self.ops.calls.index('readonly_backup'), self.ops.calls.index('stop'))
        self.assertNotIn('restore_database', self.ops.calls)

    def test_failed_candidate_uses_compatible_previous_and_keeps_dump(self):
        old = self.control.state('admin')['current']
        self.ops.health = [False, True]
        result = self.control.deploy('admin', self.incoming(self.package('bad-health')))
        self.assertEqual(result['status'], 'rolled_back')
        self.assertEqual(self.control.state('admin')['current'], old)
        self.assertTrue(list((self.cfg.state / 'backups').glob('*/database.dump')))
        self.assertNotIn('restore_database', self.ops.calls)

    def test_network_retry_of_same_release_does_not_restart_or_erase_rollback(self):
        incoming = self.incoming(self.package('idempotent'))
        self.control.deploy('admin', incoming)
        before = self.control.state('admin')
        self.ops.calls.clear()
        result = self.control.deploy('admin', incoming)
        self.assertTrue(result['unchanged'])
        self.assertEqual(self.control.state('admin'), before)
        self.assertNotIn('stop', self.ops.calls)
        self.assertNotIn('readonly_backup', self.ops.calls)

    def test_preflight_failure_leaves_live_pointer_and_service_untouched(self):
        before = self.cfg.app('admin')['current'].resolve()
        with self.assertRaises(ValueError):
            self.control.deploy('admin', self.incoming(self.package('preflight-bad', 'reject-preflight')))
        self.assertEqual(self.cfg.app('admin')['current'].resolve(), before)
        self.assertNotIn('stop', self.ops.calls)
        self.assertNotIn('readonly_backup', self.ops.calls)

    def test_process_crash_pending_receipt_recovers_previous_without_database_restore(self):
        app = self.cfg.app('admin'); value = self.control.state('admin')
        old = value['current']; candidate = self.control.prepare(app, self.package('pending'))
        value['pending'] = {'candidate': candidate, 'rollback': old, 'backup': 'synthetic'}
        self.control.save('admin', value)
        self.files.promote(app, self.control.ready(app, candidate))
        self.control.recover(app, self.control.state('admin'))
        self.assertEqual(app['current'].resolve(), self.control.ready(app, old))
        self.assertIsNone(self.control.state('admin')['pending'])

    def test_explicit_rollback_is_only_trusted_previous_release(self):
        old = self.control.state('admin')['current']
        self.control.deploy('admin', self.incoming(self.package('rollback-new')))
        result = self.control.rollback('admin')
        self.assertEqual(result['status'], 'healthy')
        self.assertEqual(self.control.state('admin')['current'], old)
        bad = dict(old, directory='../../outside')
        with self.assertRaises(ValueError): self.control.ready(self.cfg.app('admin'), bad)
        with self.assertRaises(ValueError): self.control.ready(self.cfg.app('store'), old)

    def test_first_cutover_requires_separate_compatible_fallback_and_shared_maintenance(self):
        app = self.cfg.app('admin')
        app['current'].unlink(); (self.cfg.state / 'admin.json').unlink()
        incoming = self.incoming(self.package('first'))
        with self.assertRaises(FileNotFoundError): self.control.deploy('admin', incoming)
        (self.cfg.config / 'maintenance').write_text('fixture maintenance')
        rollback = self.cfg.config / 'rollback'; rollback.mkdir()
        shutil.copyfile(self.old, rollback / 'admin.tar.gz')
        self.ops.running = True
        with self.assertRaises(RuntimeError): self.control.deploy('admin', incoming)
        self.ops.running = False
        self.assertEqual(self.control.deploy('admin', incoming)['status'], 'healthy')

    def test_stage_names_cannot_select_shells_arbitrary_paths_or_other_application(self):
        for value in ['../outside', 'admin-1-1;id', '/tmp/admin-1-1', 'store-1-1', 'admin-0-1', 'admin-1-1/../../']:
            with self.assertRaises(ValueError): stage_name('admin', value)
        self.assertEqual(stage_name('admin', 'admin-123456-2'), 'admin-123456-2')

    def test_transient_commands_drop_identity_and_bound_child_lifetime(self):
        commands = []
        ops = SystemOps(self.cfg, self.files)
        with patch.object(ops, '_run', side_effect=lambda argv, **kwargs: commands.append(argv)):
            app = self.cfg.app('admin')
            ops._transient(app, Path('/fixture/release'), ['/usr/bin/python3', '-c', 'pass'], build=True, writable=[Path('/fixture/release/.venv')])
            ops.preflight(app, Path('/fixture/release'))
        self.assertIn('--property=User=gingtto-build', commands[0])
        self.assertIn('--property=KillMode=control-group', commands[0])
        self.assertIn('--property=NoNewPrivileges=yes', commands[0])
        self.assertIn('--property=ProtectSystem=strict', commands[0])
        self.assertTrue(all('--property=User=gingtto-admin' in command for command in commands[1:]))
        self.assertTrue(all('--wait' in command and '--collect' in command for command in commands))
        self.assertIn('--property=ReadWritePaths=' + str(app['primary']/'data') + ' ' + str(app['primary']/'uploads'), commands[1])
        self.assertIn('/usr/bin/python3', commands[1])

    def test_voice_edits_preserve_signing_key_credentials_and_other_fields(self):
        raw = 'PGPASSWORD=preserved-fixture\nORDER_VOICE_CURSOR_SECRET=' + 'fixture-key-' * 4 + '\nORDER_VOICE_ENABLED=0\n'
        updated = voice_contents(raw, 'enable')
        self.assertIn('PGPASSWORD=preserved-fixture', updated)
        self.assertIn('ORDER_VOICE_CURSOR_SECRET=' + 'fixture-key-' * 4, updated)
        self.assertIn('ORDER_VOICE_ENABLED=1', updated)
        self.assertIn('ORDER_VOICE_ENABLED=0', voice_contents(updated, 'disable'))
        with self.assertRaises(ValueError): voice_contents('ORDER_VOICE_CURSOR_SECRET=short\n', 'enable')
        with self.assertRaises(ValueError): voice_contents(raw + 'ORDER_VOICE_ENABLED=1\n', 'enable')

    def test_runtime_files_have_one_authority_and_no_hidden_gunicorn_overrides(self):
        app = 'ORDER_VOICE_ENABLED=0\nORDER_VOICE_CURSOR_SECRET=' + 'fixture-key-' * 4 + '\n'
        security = 'APP_ENV=production\nDB_SCHEMA_AUTO_MIGRATE=0\nSECURITY_ATTACHMENT_MODE=legacy\nSECURITY_LOGIN_PROTECTION_ENABLED=0\nPGDATABASE=fixture_test\nPGHOST=127.0.0.1\n'
        self.assertEqual(runtime_values(app, security, 'fixture_test', 'admin')['ORDER_VOICE_ENABLED'], '0')
        for first, second in [(app + 'PGUSER=owner\n', security), (app, security + 'ORDER_VOICE_ENABLED=1\n'),
                (app + 'GUNICORN_CMD_ARGS=--env ORDER_VOICE_ENABLED=1\n', security),
                (app + 'GUNICORN_BIND=0.0.0.0:5302\n', security),
                (app, security.replace('PGHOST=127.0.0.1', 'PGHOST=db.invalid')),
                (app + 'OTHER=first\n', security + 'OTHER=second\n'),
                (app + 'SECURITY_LOGIN_PROTECTION_ENABLED=1\n', security)]:
            with self.assertRaises(ValueError): runtime_values(first, second, 'fixture_test', 'admin')

    def test_runtime_file_ambiguous_duplicates_and_escapes_are_rejected(self):
        self.assertEqual(env_values('# retained\nURL=https://fixture.invalid/a?q=b\n'), {'URL': 'https://fixture.invalid/a?q=b'})
        for raw in ['KEY=one\nKEY=two\n', 'export KEY=one\n', 'KEY="unterminated\n', 'KEY=one\\two\n']:
            with self.assertRaises(ValueError): env_values(raw)


if __name__ == '__main__': unittest.main()
