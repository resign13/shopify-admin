"""Real Media.upload acceptance: fake identity/registry, temporary files, no network."""
import ast
from contextlib import contextmanager
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from PIL import Image
from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import Unauthorized

from private_media import Media
from safe_images import MAX_BYTES


CHANNEL = 'store' if Path(__file__).parent.name == 'storefront-backend' else 'admin'
OUTPUT_LIMIT = 1_000_000


def png(size=(800, 600), **options):
    output = io.BytesIO()
    with Image.new('RGB', size, (180, 90, 30)) as picture:
        picture.save(output, 'PNG', **options)
    return output.getvalue()


class Registry:
    """Capture the real insert's parameter contract without opening a database."""
    def __init__(self):
        self.rows = []

    @contextmanager
    def get_connection(self):
        yield self

    def execute(self, sql, params):
        if not sql.lstrip().startswith('INSERT INTO security_files('):
            raise AssertionError('Unexpected database operation')
        columns = ('id', 'storage_channel', 'storage_key', 'filename', 'mime_type',
                   'byte_size', 'sha256', 'owner_channel', 'owner_id', 'purpose')
        row = dict(zip(columns, params))
        self.rows.append(row)
        return SimpleNamespace(fetchone=lambda: row)


class ImageUploadLimitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.large_png = png(compress_level=0)
        cls.small_png = png((32, 24))
        assert len(cls.large_png) > OUTPUT_LIMIT
        document = PdfWriter()
        document.add_blank_page(width=100, height=100)
        output = io.BytesIO()
        document.write(output)
        cls.pdf = output.getvalue()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {'SECURITY_ATTACHMENT_MODE': 'legacy'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = Flask(__name__)
        self.identity = Mock(current=Mock(return_value={'id': 23}))
        self.app.extensions['security'] = self.identity
        self.db = Registry()
        self.media = Media(self.app, self.db, CHANNEL, self.root / 'backend')
        self.media.roots = {c: self.root / c / 'private' for c in ('admin', 'store')}
        self.media.uploads = {c: self.root / c / 'uploads' for c in ('admin', 'store')}
        self.replicate = self.enterContext(patch('private_storage.replicate'))
        self.enterContext(patch('socket.create_connection', side_effect=AssertionError('Network is forbidden')))
        self.enterContext(self.app.test_request_context('/', base_url='https://fixture.invalid'))

    def storage(self, data=None, filename='reference.png'):
        return FileStorage(stream=io.BytesIO(self.large_png if data is None else data),
                           filename=filename, content_type='application/octet-stream')

    def files(self):
        return sorted(path for path in self.root.rglob('*') if path.is_file())

    def assert_no_storage_side_effects(self):
        self.assertEqual(self.files(), [])
        self.assertEqual(self.db.rows, [])
        self.replicate.assert_not_called()

    def assert_jpeg(self, raw):
        self.assertLessEqual(len(raw), OUTPUT_LIMIT)
        with Image.open(io.BytesIO(raw)) as picture:
            self.assertEqual(picture.format, 'JPEG')
            self.assertEqual(picture.size, (800, 600))

    def uploader(self):
        captured = []
        def upload(storage):
            captured.append((storage.read(), storage.filename, storage.mimetype))
            return 'https://fixture.invalid/external/' + storage.filename
        mock = Mock(side_effect=upload)
        self.app.extensions['legacy_media_uploader'] = mock
        return mock, captured

    def test_external_uploader_receives_normalized_jpeg_bytes_and_metadata(self):
        uploader, captured = self.uploader()
        url = self.media.upload(self.storage(), purpose='product')
        uploader.assert_called_once()
        raw, filename, mime = captured[0]
        self.assert_jpeg(raw)
        self.assertEqual((filename, mime), ('reference.jpg', 'image/jpeg'))
        self.assertTrue(url.endswith('/reference.jpg'))
        self.assert_no_storage_side_effects()

    def test_legacy_local_file_contains_normalized_jpeg(self):
        url = self.media.upload(self.storage())
        saved = self.files()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].suffix, '.jpg')
        self.assertEqual(saved[0].parent, self.media.uploads[CHANNEL])
        self.assertTrue(url.endswith('/uploads/' + saved[0].name))
        self.assert_jpeg(saved[0].read_bytes())
        self.assertEqual(self.db.rows, [])
        self.replicate.assert_not_called()

    def test_private_registry_and_replica_match_the_saved_normalized_bytes(self):
        self.media.mode = 'private'
        url = self.media.upload(self.storage(), purpose='contract')
        self.assertEqual(len(self.db.rows), 1)
        row = self.db.rows[0]
        target = self.media.roots[CHANNEL] / row['storage_key']
        self.assertEqual(self.files(), [target])
        raw = target.read_bytes()
        self.assert_jpeg(raw)
        self.assertEqual(row['mime_type'], 'image/jpeg')
        self.assertEqual(row['filename'], 'reference.jpg')
        self.assertEqual(row['storage_key'], str(row['id']) + '.jpg')
        self.assertEqual(row['byte_size'], len(raw))
        self.assertEqual((row['storage_channel'], row['owner_channel']), (CHANNEL, CHANNEL))
        self.assertEqual((row['purpose'], row['owner_id']), ('contract', 23))
        self.assertTrue(url.endswith('/content/reference.jpg'))
        self.replicate.assert_called_once_with(CHANNEL, row['storage_key'], raw, 'image/jpeg')

    def test_compliant_external_upload_retains_exact_original_bytes(self):
        _, captured = self.uploader()
        self.media.upload(self.storage(self.small_png))
        self.assertEqual(captured, [(self.small_png, 'reference.png', 'image/png')])
        self.assert_no_storage_side_effects()

    def test_compliant_legacy_local_retains_exact_original_bytes(self):
        self.media.upload(self.storage(self.small_png))
        saved = self.files()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), self.small_png)
        self.assertEqual(saved[0].suffix, '.png')

    def test_compliant_private_upload_retains_exact_original_bytes(self):
        self.media.mode = 'private'
        self.media.upload(self.storage(self.small_png))
        row = self.db.rows[0]
        self.assertEqual((self.media.roots[CHANNEL] / row['storage_key']).read_bytes(), self.small_png)
        self.assertEqual((row['mime_type'], row['byte_size']), ('image/png', len(self.small_png)))
        self.replicate.assert_called_once_with(CHANNEL, row['storage_key'], self.small_png, 'image/png')

    def test_pdf_is_byte_identical_and_never_enters_image_normalization(self):
        _, captured = self.uploader()
        with patch('image_normalization.normalize_image', side_effect=AssertionError('PDF must not enter image normalization')) as normalize:
            self.media.upload(self.storage(self.pdf, 'reference.pdf'))
            normalize.assert_not_called()
        self.assertEqual(captured, [(self.pdf, 'reference.pdf', 'application/pdf')])
        self.assert_no_storage_side_effects()

    def test_private_pdf_registration_and_replica_preserve_original(self):
        self.media.mode = 'private'
        with patch('image_normalization.normalize_image', side_effect=AssertionError('PDF must not enter image normalization')) as normalize:
            self.media.upload(self.storage(self.pdf, 'reference.pdf'))
            normalize.assert_not_called()
        row = self.db.rows[0]
        self.assertEqual(row['mime_type'], 'application/pdf')
        self.assertEqual(row['byte_size'], len(self.pdf))
        self.assertEqual((self.media.roots[CHANNEL] / row['storage_key']).read_bytes(), self.pdf)
        self.replicate.assert_called_once_with(CHANNEL, row['storage_key'], self.pdf, 'application/pdf')

    def test_spoofed_extension_is_rejected_without_storage(self):
        with self.assertRaisesRegex(ValueError, 'invalid or unsupported'):
            self.media.upload(self.storage(filename='reference.jpg'))
        self.assert_no_storage_side_effects()

    def test_original_input_limit_is_enforced_before_normalization(self):
        for mode in ('legacy', 'private'):
            with self.subTest(mode=mode):
                self.media.mode = mode
                with self.assertRaisesRegex(ValueError, 'size exceeds'):
                    self.media.upload(self.storage(), max_bytes=1024)
                self.assert_no_storage_side_effects()

    def test_default_32mib_input_limit_is_not_replaced_with_1mb(self):
        self.assertEqual(MAX_BYTES, 32 * 1024 * 1024)
        self.assertEqual(Media.upload.__kwdefaults__['max_bytes'], 32 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, 'size exceeds'):
            self.media.upload(self.storage(b'x' * (MAX_BYTES + 1)))
        self.assert_no_storage_side_effects()

    def test_unauthenticated_upload_has_no_storage_side_effects(self):
        self.identity.current.return_value = None
        for mode in ('legacy', 'private'):
            with self.subTest(mode=mode):
                self.media.mode = mode
                with self.assertRaises(Unauthorized):
                    self.media.upload(self.storage())
                self.assert_no_storage_side_effects()

    def test_store_style_10mib_original_limit_rejects_oversized_input(self):
        limit = 10 * 1024 * 1024
        with self.assertRaisesRegex(ValueError, 'size exceeds'):
            self.media.upload(self.storage(b'x' * (limit + 1)), max_bytes=limit)
        self.assert_no_storage_side_effects()

    def test_store_style_10mib_limit_accepts_and_normalizes_valid_input_at_limit(self):
        limit = 10 * 1024 * 1024
        original = self.large_png + b'\0' * (limit - len(self.large_png))
        _, captured = self.uploader()
        self.media.upload(self.storage(original), max_bytes=limit)
        self.assert_jpeg(captured[0][0])
        self.assert_no_storage_side_effects()

    def test_store_route_keeps_explicit_10mib_limit_without_importing_app(self):
        if CHANNEL != 'store':
            return
        source = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        route = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == 'upload_order_attachment')
        limits = [keyword.value for node in ast.walk(route) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == 'upload'
                  for keyword in node.keywords if keyword.arg == 'max_bytes']
        self.assertEqual(len(limits), 1)
        self.assertEqual(ast.dump(limits[0]), ast.dump(ast.parse('10*1024*1024', mode='eval').body))


if __name__ == '__main__':
    unittest.main()
