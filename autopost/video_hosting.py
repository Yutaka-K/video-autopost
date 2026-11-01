"""Threads 用に、動画を一時的にインターネット上（Cloudflare R2 / Amazon S3）に置く処理。

アップロードした動画には「2時間だけ有効な秘密のURL」を発行して Threads に渡し、
投稿が終わったら自動で削除します。バケットを一般公開する必要はありません。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from .config import Config

S3_KEYS = ("S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET")
URL_EXPIRES = 2 * 3600


def hosting_missing_settings(config: Config) -> list[str]:
    missing = [k for k in S3_KEYS if not config.get(k)]
    return [f"動画置き場の設定（{', '.join(missing)}）が .env に書かれていません"] if missing else []


class S3Hosting:
    def __init__(self, config: Config, client=None):
        self.config = config
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config as BotoConfig

            self._client = boto3.client(
                "s3",
                endpoint_url=self.config.get("S3_ENDPOINT_URL") or None,
                aws_access_key_id=self.config.get("S3_ACCESS_KEY_ID"),
                aws_secret_access_key=self.config.get("S3_SECRET_ACCESS_KEY"),
                region_name=self.config.get("S3_REGION", "auto") or "auto",
                config=BotoConfig(signature_version="s3v4"),
            )
        return self._client

    def upload(self, video: Path) -> tuple[str, str]:
        bucket = self.config.get("S3_BUCKET")
        key = f"autopost-tmp/{uuid.uuid4().hex}{video.suffix.lower()}"
        content_type = "video/quicktime" if video.suffix.lower() == ".mov" else "video/mp4"
        self.client.upload_file(str(video), bucket, key, ExtraArgs={"ContentType": content_type})
        url = self.client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=URL_EXPIRES
        )
        return key, url

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.config.get("S3_BUCKET"), Key=key)
