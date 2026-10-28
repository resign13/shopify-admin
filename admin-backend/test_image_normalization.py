"""Pure-memory normalization tests: no app, database or external media access."""
import io
import random
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, JpegImagePlugin

import image_normalization as normalization


def encoded(image, fmt='PNG', **options):
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def noise(size, mode='RGB'):
    channels = len(mode)
    data = random.Random(20261028).randbytes(size[0] * size[1] * channels)
    return Image.frombytes(mode, size, data)


class ImageNormalizationTest(unittest.TestCase):
    def assert_result(self, result):
        self.assertLessEqual(len(result.data), 1_000_000)
        self.assertEqual(result.size, len(result.data))
        with Image.open(io.BytesIO(result.data)) as image:
            self.assertEqual(Image.MIME[image.format], result.mime)
            self.assertEqual(normalization._TYPES[image.format][0], result.suffix)

    def test_compliant_original_unchanged_and_no_file_write(self):
        original = encoded(Image.new('RGB', (90, 60), 'orange'), 'JPEG')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.jpg'
            path.write_bytes(original)
            result = normalization.normalize_image(path.read_bytes())
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])
        self.assertEqual(result.data, original)
        self.assertFalse(result.changed)
        self.assert_result(result)

    def test_exact_decimal_limit_is_unchanged(self):
        original = encoded(Image.new('RGB', (8, 8), 'white'))
        original += b'\0' * (1_000_000 - len(original))
        result = normalization.normalize_image(original)
        self.assertEqual(result.data, original)
        self.assertFalse(result.changed)

    def test_photo_opaque_png_can_become_jpeg(self):
        original = encoded(noise((1000, 1000)))
        self.assertGreater(len(original), 1_000_000)
        result = normalization.normalize_image(original, purpose='product')
        self.assertTrue(result.changed)
        self.assertEqual(result.mime, 'image/jpeg')
        self.assertLessEqual(result.width, 1000)
        self.assertGreaterEqual(max(result.width, result.height), 640)
        self.assert_result(result)

    def test_transparent_alpha_preserved(self):
        image = Image.new('RGBA', (1000, 1000), (50, 100, 150, 0))
        image.paste((255, 20, 30, 128), (250, 250, 750, 750))
        original = encoded(image, compress_level=0)
        result = normalization.normalize_image(original)
        self.assertTrue(result.changed)
        self.assertIn(result.mime, ('image/png', 'image/webp'))
        with Image.open(io.BytesIO(result.data)) as output:
            self.assertEqual(output.convert('RGBA').getchannel('A').tobytes(), image.getchannel('A').tobytes())
        self.assert_result(result)

    def test_high_quality_webp_fallback_preserves_alpha(self):
        image = noise((600, 600), 'RGBA')
        original = encoded(image)
        self.assertGreater(len(original), 1_000_000)
        result = normalization.normalize_image(original)
        self.assertEqual(result.mime, 'image/webp')
        with Image.open(io.BytesIO(result.data)) as output:
            self.assertEqual(output.convert('RGBA').getchannel('A').tobytes(), image.getchannel('A').tobytes())
        self.assert_result(result)

    def test_jpeg_quality_tables_and_full_chroma_are_preserved(self):
        original = encoded(Image.new('RGB', (1800, 1000), 'orange'))
        original += b'\0' * (1_000_001 - len(original))
        result = normalization.normalize_image(original)
        reference = encoded(Image.new('RGB', (1, 1)), 'JPEG', quality=92)
        with Image.open(io.BytesIO(result.data)) as output, Image.open(io.BytesIO(reference)) as expected:
            self.assertEqual(output.quantization, expected.quantization)
            self.assertEqual(JpegImagePlugin.get_sampling(output), 0)

    def test_exif_orientation_baked_only_when_changed(self):
        image = Image.new('RGB', (1800, 1000), 'orange')
        image.paste('blue', (0, 0, 900, 1000))
        exif = Image.Exif()
        exif[274] = 6
        original = encoded(image, 'JPEG', exif=exif)
        unchanged = normalization.normalize_image(original)
        self.assertEqual(unchanged.data, original)
        # JPEG trailing padding triggers normalization without changing pixels.
        original += b'\0' * (1_000_001 - len(original))
        result = normalization.normalize_image(original)
        self.assertEqual((result.width, result.height), (1000, 1800))
        with Image.open(io.BytesIO(result.data)) as output:
            self.assertNotIn(output.getexif().get(274), (3, 6, 8))
            self.assertGreater(output.getpixel((500, 250))[2], 200)
        self.assert_result(result)

    def test_document_detail_floor_fails_not_oversized_fallback(self):
        original = encoded(noise((1600, 1600)))
        with self.assertRaisesRegex(normalization.ImageNormalizationError, 'minimum detail'):
            normalization.normalize_image(original, purpose='order')

    def test_output_hard_cap_is_rechecked(self):
        original = encoded(Image.new('RGB', (600, 600), 'white'), compress_level=0)
        with patch.object(normalization, '_static', return_value=b'x' * 1_000_001):
            with self.assertRaisesRegex(normalization.ImageNormalizationError, 'output limit'):
                normalization.normalize_image(original)

    def test_invalid_pdf_and_input_limits(self):
        for raw in (b'', b'%PDF-1.7\n', b'x' * (32 * 1024 * 1024 + 1)):
            with self.assertRaises(normalization.ImageNormalizationError):
                normalization.normalize_image(raw)
        original = encoded(Image.new('RGB', (10, 10)))
        with patch('safe_images.MAX_PIXELS', 99):
            with self.assertRaises(normalization.ImageNormalizationError):
                normalization.normalize_image(original)

    def test_animation_keeps_frames_duration_and_loop(self):
        frames = [Image.new('RGBA', (500, 500), color)
                  for color in ('red', 'green', 'blue')]
        original = encoded(frames[0], save_all=True, append_images=frames[1:],
                           duration=[100, 200, 300], loop=3, compress_level=0)
        original += b'\0' * max(0, 1_000_001 - len(original))
        self.assertGreater(len(original), 1_000_000)
        result = normalization.normalize_image(original)
        self.assertEqual(result.frames, 3)
        with Image.open(io.BytesIO(result.data)) as output:
            durations, loop = normalization._animation_metadata(output)
            self.assertEqual(durations, [100, 200, 300])
            self.assertEqual(loop, 3)
        self.assert_result(result)

    def test_small_animation_is_byte_identical(self):
        frames = [Image.new('RGB', (40, 40), c) for c in ('red', 'blue')]
        original = encoded(frames[0], 'GIF', save_all=True,
                           append_images=frames[1:], duration=[40, 80], loop=0)
        result = normalization.normalize_image(original)
        self.assertEqual(result.data, original)
        self.assertEqual(result.frames, 2)
        self.assertFalse(result.changed)

    def test_animation_budget_failure_is_explicit(self):
        frames = [Image.new('RGBA', (500, 500), c) for c in ('red', 'blue')]
        original = encoded(frames[0], save_all=True, append_images=frames[1:],
                           duration=100, loop=0, compress_level=0)
        original += b'\0' * max(0, 1_000_001 - len(original))
        with patch.object(normalization, 'MAX_ANIMATION_PIXELS', 100):
            with self.assertRaisesRegex(normalization.ImageNormalizationError, 'reencoding budget'):
                normalization.normalize_image(original)

    def test_more_than_100_frames_is_rejected_even_when_small(self):
        frames = [Image.new('RGB', (4, 4), (i, 0, 0)) for i in range(101)]
        original = encoded(frames[0], save_all=True, append_images=frames[1:],
                           duration=10, loop=0)
        with self.assertRaises(normalization.ImageNormalizationError):
            normalization.normalize_image(original)

    def test_animation_encoding_that_drops_frames_fails(self):
        frames = [Image.new('RGBA', (20, 20), c) for c in ('red', 'blue')]
        original = encoded(frames[0], save_all=True, append_images=frames[1:], duration=100, loop=0)
        original += b'\0' * (1_000_001 - len(original))
        flat = encoded(Image.new('RGB', (20, 20), 'red'), 'WEBP')
        with patch.object(normalization, '_encode', return_value=flat):
            with self.assertRaisesRegex(normalization.ImageNormalizationError, 'preserving frames'):
                normalization.normalize_image(original)


if __name__ == '__main__':
    unittest.main()
