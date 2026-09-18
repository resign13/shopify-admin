"""Bounded local/R2 image delivery. Originals are never modified."""
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import tempfile
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from filelock import FileLock, Timeout
from flask import jsonify, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import safe_join

WIDTHS = {160, 320, 640, 960, 1600}
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 40_000_000
SOURCE_TTL = 3600
CACHE_BUDGET = 1024 * 1024 * 1024


@lru_cache(maxsize=1)
def r2_client():
    return boto3.client(
        "s3", region_name="auto",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        config=Config(connect_timeout=3, read_timeout=8,
                      retries={"total_max_attempts": 2}, max_pool_connections=16),
    )


def atomic_write(path, writer):
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as output:
            writer(output)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def prune_cache(cache, protected):
    # Fixed-size lock stripes avoid accumulating a lock file for every URL.
    with FileLock(str(cache / "cleanup.lock"), timeout=10):
        files = []
        for path in cache.iterdir():
            if path.suffix not in {".source", ".webp"}:
                continue
            try:
                stat = path.stat()
                files.append((stat.st_mtime, stat.st_size, path))
            except FileNotFoundError:
                pass
        total = sum(size for _, size, _ in files)
        for modified, size, path in sorted(files):
            if total <= CACHE_BUDGET:
                break
            # Other requests may be streaming recently generated files.
            if path in protected or modified > time.time() - 60:
                continue
            path.unlink(missing_ok=True)
            total -= size


def error_response(message, status):
    response = jsonify({"message": message})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def deliver_image(upload_dir, cache, filename, logger):
    joined = safe_join(str(upload_dir), filename)
    if not joined or "\\" in filename:
        return error_response("Not found", 404)
    source = Path(joined)
    if not source.resolve().is_relative_to(Path(upload_dir).resolve()):
        return error_response("Not found", 404)
    width = request.args.get("w")
    if width is not None and width not in {str(value) for value in WIDTHS}:
        return error_response("Unsupported image width", 400)
    width = int(width) if width else None
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(filename.encode()).hexdigest()
    try:
        with FileLock(str(cache / f"stripe-{int(key[:2], 16) % 64}.lock"), timeout=20):
            wrote_cache = False
            if not source.is_file():
                source = cache / f"{key}.source"
                if not source.exists() or time.time() - source.stat().st_mtime > SOURCE_TTL:
                    obj = r2_client().get_object(Bucket=os.environ["R2_BUCKET"], Key=filename)
                    body = obj["Body"]
                    try:
                        if obj.get("ContentLength", 0) > MAX_SOURCE_BYTES:
                            return error_response("Image is too large", 413)
                        def download(output):
                            total = 0
                            while chunk := body.read(256 * 1024):
                                total += len(chunk)
                                if total > MAX_SOURCE_BYTES:
                                    raise ValueError("Source exceeds image size limit")
                                output.write(chunk)
                        atomic_write(source, download)
                        wrote_cache = True
                    finally:
                        body.close()
            target = source
            optimized = False
            if width:
                stat = source.stat()
                if stat.st_size > MAX_SOURCE_BYTES:
                    return error_response("Image is too large", 413)
                version = hashlib.sha256(f"{key}:{stat.st_mtime_ns}:{stat.st_size}:v1".encode()).hexdigest()
                variant = cache / f"{version}-{width}.webp"
                if not variant.exists():
                    try:
                        with Image.open(source) as original:
                            if original.width * original.height > MAX_PIXELS:
                                return error_response("Image dimensions are too large", 413)
                            if not getattr(original, "is_animated", False):
                                original.draft("RGB", (width, width))
                                image = ImageOps.exif_transpose(original)
                                image.thumbnail((width, width * 4), Image.Resampling.LANCZOS)
                                image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
                                atomic_write(variant, lambda output: image.save(output, "WEBP", quality=82, method=4))
                                wrote_cache = True
                    except (UnidentifiedImageError, OSError):
                        # PDFs, animated and unsupported files retain their original representation.
                        pass
                if variant.exists():
                    target, optimized = variant, True
            response = send_file(target, mimetype="image/webp" if optimized else None,
                                 download_name=Path(filename).name,
                                 conditional=True, max_age=3600)
            response.headers["Cache-Control"] = "public, max-age=3600"
            response.headers["X-Content-Type-Options"] = "nosniff"
            if wrote_cache:
                try:
                    prune_cache(cache, {source, target})
                except (OSError, Timeout):
                    logger.warning("Image cache cleanup deferred")
            return response
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
            return error_response("Not found", 404)
        logger.exception("R2 image retrieval failed")
    except (Image.DecompressionBombError, ValueError):
        return error_response("Image exceeds processing limits", 413)
    except Exception:
        logger.exception("Image delivery failed")
    return error_response("Image storage temporarily unavailable", 503)
