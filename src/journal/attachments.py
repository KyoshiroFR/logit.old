"""Validation des captures : uniquement de vraies images PNG, JPEG ou WebP, taille et nombre limités."""
import hashlib
from io import BytesIO

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from .models import Attachment

Image.MAX_IMAGE_PIXELS = 50_000_000  # protège contre les « bombes » de décompression


def build_attachments(files, already=0):
    if already + len(files) > Attachment.MAX_PER_INTERVENTION:
        raise ValidationError(f"{Attachment.MAX_PER_INTERVENTION} captures au maximum par fiche.")
    built = []
    for upload in files:
        if upload.size > Attachment.MAX_BYTES:
            raise ValidationError(f"« {upload.name} » dépasse 5 Mo.")
        data = upload.read()
        try:
            with Image.open(BytesIO(data)) as probe:
                image_format = probe.format
                probe.verify()
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
            raise ValidationError(f"« {upload.name} » n’est pas une image valide.")
        if image_format not in Attachment.TYPES:
            raise ValidationError(f"« {upload.name} » : seuls PNG, JPEG et WebP sont acceptés.")
        name = (upload.name or "capture").replace("/", "_").replace("\\", "_")[:200]
        built.append(Attachment(name=name, content_type=Attachment.TYPES[image_format], size=len(data),
                                width=width, height=height, sha256=hashlib.sha256(data).hexdigest(), data=data))
    return built
