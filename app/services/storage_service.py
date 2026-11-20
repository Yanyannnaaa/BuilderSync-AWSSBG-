"""Rule B: filename standardisation + S3 routing."""
import re
from datetime import date
from typing import BinaryIO

import boto3

from app.config import get_settings
from app.models import User

ALLOWED_EXTENSIONS = {"pdf", "docx", "png"}


def sanitize(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def format_name(user: User) -> str:
    """LASTNAME_FIRSTNAME, e.g. Dela Cruz / Juan -> DELA_CRUZ_JUAN."""
    return "_".join(p for p in (sanitize(user.last_name), sanitize(user.first_name)) if p)


def get_extension(filename: str) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext if ext in ALLOWED_EXTENSIONS else None


def standardized_filename(user: User, requirement_type: str, ext: str, on: date | None = None) -> str:
    on = on or date.today()
    return (
        f"Y{user.year_level}_{user.student_number}_{format_name(user)}_"
        f"{sanitize(requirement_type)}_{on:%Y%m%d}.{ext}"
    )


def build_key(user: User, requirement_type: str, filename: str) -> str:
    return f"submissions/{user.role.value}/{requirement_type}/{filename}"


def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        region_name=s.aws_region,
        aws_access_key_id=s.aws_access_key_id or None,
        aws_secret_access_key=s.aws_secret_access_key or None,
    )


def s3_configured() -> bool:
    return bool(get_settings().s3_bucket_name)


CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
}


def upload_stream(fileobj: BinaryIO, key: str, ext: str) -> None:
    _client().upload_fileobj(
        fileobj,
        get_settings().s3_bucket_name,
        key,
        ExtraArgs={"ContentType": CONTENT_TYPES[ext], "ServerSideEncryption": "AES256"},
    )


def presigned_download_url(key: str, filename: str) -> tuple[str, int]:
    s = get_settings()
    url = _client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": s.s3_bucket_name,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=s.s3_presign_seconds,
    )
    return url, s.s3_presign_seconds
