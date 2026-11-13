"""Order-note image encoding; product thumbnails keep their existing policy."""
from io import BytesIO

from PIL import Image, ImageOps

NOTE_PIXELS = 2400
ORIGINAL_PASSTHROUGH_BYTES = 1_000_000
NOTE_ENCODING = 'note-original-png-jpeg90-v1'


def encode_note_image(raw: bytes, pixels: int = NOTE_PIXELS) -> bytes:
    with Image.open(BytesIO(raw)) as image:
        png = image.format == 'PNG'
        upright = image.getexif().get(274, 1) == 1
        fits = max(image.size) <= pixels
        if image.format in {'PNG', 'JPEG'} and upright and fits and len(raw) <= ORIGINAL_PASSTHROUGH_BYTES:
            return raw

        converted = ImageOps.exif_transpose(image).convert('RGBA')
        converted.thumbnail((pixels, pixels), Image.Resampling.LANCZOS)
        output = BytesIO()
        if png or converted.getextrema()[3][0] != 255:
            converted.save(output, format='PNG')
            # A recompressed legacy PNG must not grow when no pixel change was needed.
            if png and upright and fits and len(raw) <= output.tell():
                return raw
        else:
            converted.convert('RGB').save(output, format='JPEG', quality=90, subsampling=0)
        return output.getvalue()
