import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('voice_settings', Path(__file__).with_name('configure-order-voice.py'))
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / '.env'
        self.path.write_text('PGPASSWORD=preserved-fixture\nOTHER=value\n', encoding='utf-8')

    def test_initial_disabled_private_key_and_repeated_ensure(self):
        self.assertEqual(settings.configure(self.path, 'ensure'), {'enabled': False, 'changed': True})
        first = self.path.read_text()
        self.assertIn('PGPASSWORD=preserved-fixture', first)
        self.assertIn('ORDER_VOICE_ENABLED=0', first)
        self.assertGreaterEqual(len(first.split('ORDER_VOICE_CURSOR_SECRET=')[1].splitlines()[0]), 32)
        self.assertEqual(settings.configure(self.path, 'ensure'), {'enabled': False, 'changed': False})
        self.assertEqual(first, self.path.read_text())
        self.assertEqual(len(list(self.path.parent.glob('.env.voice-backup-*'))), 1)

    def test_explicit_enable_disable_preserves_key_and_other_fields(self):
        settings.configure(self.path, 'ensure')
        original_key = self.path.read_text().split('ORDER_VOICE_CURSOR_SECRET=')[1].splitlines()[0]
        self.assertTrue(settings.configure(self.path, 'enable')['enabled'])
        self.assertTrue(settings.configure(self.path, 'ensure')['enabled'])
        self.assertFalse(settings.configure(self.path, 'disable')['enabled'])
        self.assertIn('ORDER_VOICE_CURSOR_SECRET=' + original_key, self.path.read_text())
        self.assertIn('OTHER=value', self.path.read_text())

    def test_invalid_active_secret_is_not_silently_rotated(self):
        self.path.write_text('ORDER_VOICE_ENABLED=1\nORDER_VOICE_CURSOR_SECRET=short\n')
        before = self.path.read_text()
        with self.assertRaises(ValueError):
            settings.configure(self.path, 'ensure')
        self.assertEqual(before, self.path.read_text())
        self.assertFalse(settings.configure(self.path, 'disable')['enabled'])

    def test_duplicate_keys_fail_without_configuration_changes(self):
        self.path.write_text('ORDER_VOICE_ENABLED=0\nORDER_VOICE_ENABLED=1\n')
        before = self.path.read_text()
        with self.assertRaises(ValueError):
            settings.configure(self.path, 'enable')
        self.assertEqual(before, self.path.read_text())


if __name__ == '__main__':
    unittest.main()
