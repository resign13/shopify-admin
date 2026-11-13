"""Pure image regressions: no database, network, or original-file changes."""
from io import BytesIO
import unittest

from PIL import Image, JpegImagePlugin

from export_image_quality import NOTE_PIXELS, encode_note_image


def encoded(image, fmt='PNG', **options):
    output = BytesIO()
    image.save(output, format=fmt, **options)
    return output.getvalue()


class NoteImageQualityTest(unittest.TestCase):
    def test_small_opaque_palette_and_transparent_png_keep_exact_bytes(self):
        for mode, color in [('RGB', '#fefefe'), ('RGBA', (10, 20, 30, 40)), ('P', 1)]:
            with self.subTest(mode=mode):
                raw = encoded(Image.new(mode, (1045, 674), color))
                self.assertEqual(encode_note_image(raw), raw)

    def test_large_png_stays_lossless_png_at_2400_pixels(self):
        source = Image.new('RGBA', (1800, 3600), (20, 40, 60, 90))
        raw = encoded(source)
        result = encode_note_image(raw)
        with Image.open(BytesIO(result)) as picture:
            self.assertEqual(picture.format, 'PNG')
            self.assertEqual(picture.size, (1200, NOTE_PIXELS))
            expected = source.resize((1200, NOTE_PIXELS), Image.Resampling.LANCZOS)
            self.assertEqual(picture.tobytes(), expected.tobytes())

    def test_oversized_legacy_png_is_recompressed_without_lossy_conversion(self):
        source = Image.new('RGB', (800, 600), 'white')
        raw = encoded(source, compress_level=0)
        self.assertGreater(len(raw), 1_000_000)
        result = encode_note_image(raw)
        self.assertLess(len(result), len(raw))
        with Image.open(BytesIO(result)) as picture:
            self.assertEqual(picture.format, 'PNG')
            self.assertEqual(picture.convert('RGB').tobytes(), source.tobytes())

    def test_png_exif_orientation_is_baked_only_when_needed(self):
        exif = Image.Exif()
        exif[274] = 6
        raw = encoded(Image.new('RGB', (300, 500), 'navy'), exif=exif)
        result = encode_note_image(raw)
        with Image.open(BytesIO(result)) as picture:
            self.assertEqual(picture.format, 'PNG')
            self.assertEqual(picture.size, (500, 300))
            self.assertEqual(picture.getexif().get(274, 1), 1)

    def test_resized_photos_use_full_chroma_quality90(self):
        raw = encoded(Image.new('RGB', (3000, 4000), 'navy'), 'JPEG')
        result = encode_note_image(raw)
        reference = encoded(Image.new('RGB', (1, 1)), 'JPEG', quality=90)
        with Image.open(BytesIO(result)) as picture, Image.open(BytesIO(reference)) as quality:
            self.assertEqual(picture.format, 'JPEG')
            self.assertEqual(picture.size, (1800, 2400))
            self.assertEqual(JpegImagePlugin.get_sampling(picture), 0)
            self.assertEqual(picture.quantization, quality.quantization)

    def test_small_jpeg_does_not_upscale_or_suffer_another_lossy_encoding(self):
        raw = encoded(Image.new('RGB', (465, 572), 'navy'), 'JPEG')
        self.assertEqual(encode_note_image(raw), raw)


if __name__ == '__main__':
    unittest.main()
