"""Photo preprocessing before any model sees it."""

import io

from PIL import Image, ImageOps

MAX_SIDE = 1024


def prepare_image(image_bytes, max_side=MAX_SIDE):
    """Upright, RGB, at most `max_side` px on the long side, as JPEG bytes.
    Raises PIL.UnidentifiedImageError (an OSError) for data that isn't an image."""
    image = Image.open(io.BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()
