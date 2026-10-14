import io
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import tarfile
import unittest
from build_release import build, verify, required, MANIFEST, allowed


class ReleaseArchiveTest(unittest.TestCase):
    def fixture(self, root):
        for name in required('admin'):
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('synthetic source')
        for name in ['admin-backend/.env', 'admin-backend/.env.security', 'admin-backend/uploads/customer.png', 'admin-backend/data/session.json', 'admin-backend/test_fixture.py', 'admin-backend/data/backup.dump', 'admin-backend/orders.xlsx', 'admin-backend/customers.csv', 'admin-backend/snapshot.json', 'admin-backend/credentials.txt']:
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('must not ship')

    def test_release_and_rollback_profile_excludes_runtime_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / 'source'; root.mkdir(); self.fixture(root)
            path = Path(directory) / 'release.tar.gz'
            result = build(root, path, 'admin')
            self.assertEqual(result['profile'], 'browser-cookie-phase1')
            self.assertTrue(result['dataFree'])
            with tarfile.open(path) as archive:
                names = archive.getnames()
                self.assertEqual(set(names), required('admin') | {MANIFEST})
            self.assertEqual(verify(path, 'admin'), result)
            with self.assertRaises(ValueError): verify(path, 'store')
            with self.assertRaises(ValueError): build(root, path, 'admin')

    def test_legacy_or_tampered_backup_is_rejected_without_extraction(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.tar.gz'
            for name, body in [('admin-backend/app.py', b'legacy'), (MANIFEST, b'{"profile":"wrong"}')]:
                with tarfile.open(path, 'w:gz') as archive:
                    item = tarfile.TarInfo(name); item.size = len(body); archive.addfile(item, io.BytesIO(body))
                with self.assertRaises(ValueError): verify(path, 'admin')

    def test_unsafe_paths_are_not_release_entries(self):
        for name in ['../app.py', '/etc/passwd', 'C:/secret.key', 'admin-backend/.env.voice-backup', 'admin-backend/data/session.json', 'admin-backend/uploads/photo.png', 'a\\b.py']:
            self.assertFalse(allowed(name), name)

    def test_changed_file_does_not_pass_manifest_hash(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / 'source'; root.mkdir(); self.fixture(root)
            source = Path(directory) / 'source.tar.gz'; build(root, source, 'admin')
            target = Path(directory) / 'tampered.tar.gz'
            with tarfile.open(source) as archive, tarfile.open(target, 'w:gz') as out:
                for item in archive:
                    raw = archive.extractfile(item).read()
                    if item.name == 'admin-backend/app.py': raw += b'changed'; item.size = len(raw)
                    out.addfile(item, io.BytesIO(raw))
            with self.assertRaisesRegex(ValueError, 'checksum'):
                verify(target, 'admin')

    def test_oversized_extension_or_member_is_rejected_before_payload_read(self):
        with TemporaryDirectory() as directory:
            for kind, size, reason in [(tarfile.XHDTYPE, 65537, 'metadata'), (tarfile.GNUTYPE_LONGNAME, 65537, 'metadata'),
                    (tarfile.REGTYPE, 512 * 1024 * 1024 + 1, 'size'), (tarfile.GNUTYPE_SPARSE, 0, 'Sparse')]:
                path = Path(directory) / ('oversized-' + kind.decode() + '.tar.gz')
                header = tarfile.TarInfo('admin-backend/app.py'); header.type = kind; header.size = size
                # The declared payload is deliberately absent: rejection must
                # happen at the header, not after allocating/decompressing it.
                with gzip.open(path, 'wb') as output: output.write(header.tobuf(format=tarfile.USTAR_FORMAT))
                with self.assertRaisesRegex(ValueError, reason): verify(path, 'admin')


if __name__ == '__main__': unittest.main()
