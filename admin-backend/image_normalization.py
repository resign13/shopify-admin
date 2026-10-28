"""In-memory upload derivatives with a decimal 1 MB output ceiling.

No storage, database or network access. Callers retain originals separately.
"""
from dataclasses import dataclass
import io

from PIL import Image, ImageOps

from safe_images import check_image


MAX_OUTPUT_BYTES = 1_000_000
# A working-set bound for reencoding, not an additional upload-size limit.
MAX_ANIMATION_PIXELS = 100_000_000
_TYPES = {
    'JPEG': ('.jpg', 'image/jpeg'), 'MPO': ('.jpg', 'image/jpeg'),
    'PNG': ('.png', 'image/png'), 'WEBP': ('.webp', 'image/webp'),
    'GIF': ('.gif', 'image/gif'), 'BMP': ('.bmp', 'image/bmp'),
    'AVIF': ('.avif', 'image/avif'),
}


class ImageNormalizationError(ValueError):
    """Invalid input or no acceptable derivative within the hard ceiling."""


@dataclass(frozen=True)
class NormalizedImage:
    data: bytes
    suffix: str
    mime: str
    changed: bool
    original_size: int
    size: int
    width: int
    height: int
    frames: int


def _result(data, original_size, changed):
    if len(data) > MAX_OUTPUT_BYTES:
        raise ImageNormalizationError('Image exceeds the 1,000,000-byte output limit')
    with Image.open(io.BytesIO(data)) as image:
        suffix, mime = _TYPES[image.format]
        return NormalizedImage(data, suffix, mime, changed, original_size,
                               len(data), image.width, image.height,
                               getattr(image, 'n_frames', 1))


def _sizes(size, purpose):
    """Original dimensions, then 0.85 steps down to the explicit detail floor."""
    longest = max(size)
    floor = min(longest, 640 if purpose == 'product' else 1600)
    edge = longest
    while True:
        yield (max(1, round(size[0] * edge / longest)),
               max(1, round(size[1] * edge / longest)))
        if edge == floor:
            return
        edge = max(floor, int(edge * .85))


def _encode(image, fmt, **options):
    if image.info.get('icc_profile'):
        options.setdefault('icc_profile', image.info['icc_profile'])
    if fmt == 'JPEG' and options.get('optimize'):
        # Pillow 11's Q90/92 optimized 4:4:4 buffer is only one byte/pixel,
        # insufficient for detailed photos. Explicit, identical quality tables
        # select its larger quality=-1 buffer without global state or disk I/O.
        probe = io.BytesIO()
        Image.new('RGB', (1, 1)).save(probe, 'JPEG', quality=options['quality'])
        with Image.open(io.BytesIO(probe.getvalue())) as sample:
            options['qtables'] = sample.quantization
        options['quality'] = -1
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def _static(image, purpose):
    # Bake the camera's display orientation into pixels before any resizing.
    image = ImageOps.exif_transpose(image)
    alpha = 'A' in image.getbands() or 'transparency' in image.info
    image = image.convert('RGBA' if alpha else 'RGB')
    if alpha:
        # Two bounded lossless attempts at the original resolution only.
        for fmt, options in (
            ('PNG', {'optimize': True}),
            ('WEBP', {'lossless': True, 'method': 1, 'exact': True}),
        ):
            candidate = _encode(image, fmt, **options)
            if len(candidate) <= MAX_OUTPUT_BYTES:
                return candidate
    for size in _sizes(image.size, purpose):
        current = image if size == image.size else image.resize(size, Image.Resampling.LANCZOS)
        for quality in (92, 90):
            if alpha:
                candidate = _encode(current, 'WEBP', quality=quality, method=1, exact=True)
            else:
                candidate = _encode(current, 'JPEG', quality=quality, subsampling=0, optimize=True)
            if len(candidate) <= MAX_OUTPUT_BYTES:
                return candidate
    raise ImageNormalizationError('Image cannot fit 1,000,000 bytes at the minimum detail dimensions')


def _animation_metadata(image):
    durations = []
    loop = image.info.get('loop', 1)
    for index in range(image.n_frames):
        image.seek(index)
        image.load()  # WebP exposes frame duration after decoding the frame.
        durations.append(image.info.get('duration', 0))
    return durations, loop


def _animation_matches(candidate, count, durations, loop):
    with Image.open(io.BytesIO(candidate)) as encoded:
        if getattr(encoded, 'n_frames', 1) != count:
            return False
        actual_durations, actual_loop = _animation_metadata(encoded)
        return actual_durations == durations and actual_loop == loop


def _animated(image, purpose):
    count = image.n_frames
    if image.width * image.height * count > MAX_ANIMATION_PIXELS:
        raise ImageNormalizationError('Animation exceeds the 100-megapixel reencoding budget')
    # APNG poster frames are not playback frames. Avoid silently changing their
    # relationship when encoding a different animation container.
    if image.info.get('default_image') or image.format == 'MPO':
        raise ImageNormalizationError('This multi-picture container needs manual normalization')
    durations, loop = _animation_metadata(image)
    frames = []
    for index in range(count):
        image.seek(index)
        frames.append(ImageOps.exif_transpose(image).convert('RGBA'))
    try:
        for size in _sizes(frames[0].size, purpose):
            current = [f if f.size == size else f.resize(size, Image.Resampling.LANCZOS)
                       for f in frames]
            try:
                # Preserve all frames rather than accidentally exporting only frame 0.
                for quality in (92, 90):
                    candidate = _encode(current[0], 'WEBP', save_all=True,
                                        append_images=current[1:], duration=durations,
                                        loop=loop, quality=quality, method=1,
                                        minimize_size=False, allow_mixed=False)
                    if len(candidate) <= MAX_OUTPUT_BYTES and _animation_matches(
                            candidate, count, durations, loop):
                        return candidate
            finally:
                for frame, original in zip(current, frames):
                    if frame is not original:
                        frame.close()
    finally:
        for frame in frames:
            frame.close()
    raise ImageNormalizationError('Animation cannot fit the output limit while preserving frames and timing')


def normalize_image(data: bytes, *, purpose: str = 'document') -> NormalizedImage:
    """Validate an image and return matching bytes/suffix/MIME, or fail.

    ``product`` has a 640px long-edge floor; all order/contract/document
    purposes use min(original long edge, 1600). Existing inputs up to 32 MiB,
    40 MP per frame and 100 frames use the shared validator. PDF is excluded.
    Compliant files, including animation and EXIF, retain their exact bytes.
    """
    try:
        check_image(data)
        if len(data) <= MAX_OUTPUT_BYTES:
            return _result(data, len(data), False)
        with Image.open(io.BytesIO(data)) as image:
            if getattr(image, 'n_frames', 1) > 1:
                candidate = _animated(image, purpose)
            else:
                image.load()
                candidate = _static(image, purpose)
        return _result(candidate, len(data), True)
    except ImageNormalizationError:
        raise
    except (OSError, ValueError, KeyError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ImageNormalizationError('Image content is invalid or cannot be normalized') from exc
