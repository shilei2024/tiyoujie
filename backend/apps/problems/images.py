import hashlib
import io
import warnings

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

from config.errors import AppError

FORMATS = {"JPEG": {"image/jpeg"}, "PNG": {"image/png"}, "WEBP": {"image/webp"}}


def encode(image):
    image = ImageOps.exif_transpose(image)
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, "white")
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        image = canvas
    else:
        image = image.convert("RGB")
    # Copy pixels into a fresh image: do not preserve EXIF/ICC/XMP/comments or trailing payloads.
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    buffer = io.BytesIO()
    clean.save(buffer, "JPEG", quality=90)
    data = buffer.getvalue()
    if len(data) > settings.IMAGE_MAX_BYTES:
        raise AppError("UPLOAD_TOO_LARGE", "处理后的图片过大，请缩小后重试。", 413)
    return data, clean.width, clean.height, hashlib.sha256(data).hexdigest()


def normalize(upload):
    if not 0 < upload.size <= settings.IMAGE_MAX_BYTES:
        raise AppError("UPLOAD_TOO_LARGE", "图片须在 8 MB 以内。", 413)
    data = upload.read(settings.IMAGE_MAX_BYTES + 1)
    if len(data) != upload.size:
        raise AppError("UPLOAD_INVALID", "图片读取不完整。", 400)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format not in FORMATS or getattr(probe, "n_frames", 1) != 1:
                    raise ValueError()
                if upload.content_type not in FORMATS[probe.format] | {"application/octet-stream"}:
                    raise ValueError()
                if (
                    probe.width * probe.height > settings.IMAGE_MAX_PIXELS
                    or max(probe.size) > settings.IMAGE_MAX_SIDE
                ):
                    raise ValueError()
                probe.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                return encode(image)
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise AppError("UPLOAD_INVALID", "仅支持有界的单帧 JPEG、PNG 或 WebP 图片。", 400) from None


def transform(content, region):
    with Image.open(io.BytesIO(content)) as image:
        x, y, width, height = (region[name] for name in ("x", "y", "width", "height"))
        if (
            min(x, y) < 0
            or min(width, height) < 1
            or x + width > image.width
            or y + height > image.height
        ):
            raise AppError("CROP_INVALID", "裁剪区域超出了图片范围。", 400)
        image = image.crop((x, y, x + width, y + height))
        return encode(image.rotate(-region["rotation"], expand=True))
