from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.config import Config

from src.ingestion.config import settings

logger = logging.getLogger(__name__)


class R2Client:
    """Cloudflare R2 storage client for raw and derived objects."""

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url or None,
            aws_access_key_id=settings.r2_access_key_id or None,
            aws_secret_access_key=settings.r2_secret_access_key or None,
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                signature_version="s3v4",
            ),
            region_name="auto",
        )
        self._bucket = settings.r2_bucket_name

    def _raw_key(
        self, source_slug: str, external_id: str, filename: str = "original"
    ) -> str:
        now = datetime.now(timezone.utc)
        return (
            f"raw/{source_slug}/{now.year}/{now.month:02d}/{now.day:02d}"
            f"/{external_id}/{filename}"
        )

    def _derived_key(
        self, source_slug: str, source_record_id: str, path: str
    ) -> str:
        return f"derived/{source_slug}/{source_record_id}/{path}"

    @staticmethod
    def compute_checksum(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def upload_raw(
        self,
        source_slug: str,
        external_id: str,
        data: bytes,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Upload raw content and optional metadata sidecar.

        Returns (r2_key, checksum).
        """
        r2_key = self._raw_key(source_slug, external_id)
        checksum = self.compute_checksum(data)

        extra_args: dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type

        self._client.put_object(
            Bucket=self._bucket,
            Key=r2_key,
            Body=data,
            **extra_args,
        )
        logger.info("Uploaded raw object: %s (%d bytes)", r2_key, len(data))

        if metadata:
            meta_key = self._raw_key(source_slug, external_id, "metadata.json")
            self._client.put_object(
                Bucket=self._bucket,
                Key=meta_key,
                Body=json.dumps(metadata, default=str).encode(),
                ContentType="application/json",
            )

        return r2_key, checksum

    def upload_image(
        self,
        source_slug: str,
        external_id: str,
        image_index: int,
        data: bytes,
        content_type: str = "image/jpeg",
    ) -> tuple[str, str]:
        """Upload an image file to R2. Returns (r2_key, checksum)."""
        ext = "jpg"
        if "png" in content_type:
            ext = "png"
        elif "gif" in content_type:
            ext = "gif"
        elif "webp" in content_type:
            ext = "webp"
        elif "tif" in content_type:
            ext = "tiff"

        now = datetime.now(timezone.utc)
        r2_key = (
            f"images/{source_slug}/{now.year}/{now.month:02d}/{now.day:02d}"
            f"/{external_id}/img_{image_index:03d}.{ext}"
        )
        checksum = self.compute_checksum(data)

        self._client.put_object(
            Bucket=self._bucket,
            Key=r2_key,
            Body=data,
            ContentType=content_type,
        )
        logger.info("Uploaded image: %s (%d bytes)", r2_key, len(data))
        return r2_key, checksum

    def upload_derived(
        self,
        source_slug: str,
        source_record_id: str,
        path: str,
        data: bytes,
        content_type: str = "application/json",
    ) -> str:
        """Upload a derived file. Returns the R2 key."""
        r2_key = self._derived_key(source_slug, source_record_id, path)
        self._client.put_object(
            Bucket=self._bucket,
            Key=r2_key,
            Body=data,
            ContentType=content_type,
        )
        logger.info("Uploaded derived object: %s", r2_key)
        return r2_key

    def download(self, r2_key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=r2_key)
        return response["Body"].read()

    def exists(self, r2_key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=r2_key)
            return True
        except self._client.exceptions.ClientError:
            return False

    def delete(self, r2_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=r2_key)

    def list_keys(self, prefix: str, max_keys: int = 1000) -> list[str]:
        response = self._client.list_objects_v2(
            Bucket=self._bucket, Prefix=prefix, MaxKeys=max_keys
        )
        return [obj["Key"] for obj in response.get("Contents", [])]


r2_client = R2Client()
