"""Credentials and validation for RunPod's podless network-volume S3 API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Callable

from backend.core.cluster_ssh import RunResult


@dataclass(frozen=True)
class S3Credentials:
    access_key: str
    secret_key: str
    source: str


def credentials_path() -> Path:
    return Path.home() / ".config" / "nadoc" / "runpod_s3.json"


def resolve_credentials() -> S3Credentials | None:
    access = os.environ.get("RUNPOD_S3_ACCESS_KEY", "").strip()
    secret = os.environ.get("RUNPOD_S3_SECRET_KEY", "").strip()
    if access and secret:
        return S3Credentials(access, secret, "env")
    try:
        data = json.loads(credentials_path().read_text())
    except (FileNotFoundError, OSError, ValueError):
        return None
    access = str(data.get("access_key") or "").strip()
    secret = str(data.get("secret_key") or "").strip()
    return S3Credentials(access, secret, "file") if access and secret else None


def save_credentials(access_key: str, secret_key: str) -> None:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"access_key": access_key, "secret_key": secret_key}))
    tmp.chmod(0o600)
    tmp.replace(path)
    path.chmod(0o600)


def endpoint_for(data_center_id: str) -> str:
    dc = data_center_id.strip().lower()
    if not dc:
        raise ValueError("the selected volume has no datacenter")
    return f"https://s3api-{dc}.runpod.io/"


def validate_credentials(
    credentials: S3Credentials, *, volume_id: str, data_center_id: str
) -> None:
    """Prove the pair can access the selected volume without launching compute."""
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        aws_access_key_id=credentials.access_key,
        aws_secret_access_key=credentials.secret_key,
        region_name=data_center_id,
        endpoint_url=endpoint_for(data_center_id),
        config=Config(connect_timeout=15, read_timeout=30, retries={"max_attempts": 3}),
    )
    client.head_bucket(Bucket=volume_id)


class RunpodS3Connection:
    """Small md_executor connection adapter backed by the network-volume S3 API."""

    def __init__(self, credentials: S3Credentials, *, volume_id: str, data_center_id: str, remote_root: str):
        import boto3
        from botocore.config import Config

        self.volume_id = volume_id
        self.remote_root = remote_root.strip("/")
        if self.remote_root.startswith("workspace/"):
            self.remote_root = self.remote_root[len("workspace/"):]
        self._client = boto3.client(
            "s3", aws_access_key_id=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            region_name=data_center_id, endpoint_url=endpoint_for(data_center_id),
            config=Config(connect_timeout=20, read_timeout=7200, retries={"max_attempts": 10}),
        )

    async def mirror(self, _src: str, _dst: str) -> RunResult:
        return RunResult(rc=0, stdout="", stderr="")

    async def run(self, _cmd: str, **_kwargs) -> RunResult:
        """Return the inventory format consumed by md_executor.remote_output_inventory."""
        import asyncio

        def listing() -> str:
            prefix = self.remote_root.rstrip("/") + "/"
            paginator = self._client.get_paginator("list_objects_v2")
            lines = []
            for page in paginator.paginate(Bucket=self.volume_id, Prefix=prefix):
                for obj in page.get("Contents", []):
                    rel = obj["Key"][len(prefix):]
                    top_log = "/" not in rel and rel.endswith((".log", ".out", ".err"))
                    if rel.startswith("output/") or top_log:
                        lines.append(f"{int(obj['Size'])}\t{rel}")
            return "\n".join(lines)

        return RunResult(rc=0, stdout=await asyncio.to_thread(listing), stderr="")

    async def sftp_get(
        self, remote_path: str, local_path: str, *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        import asyncio

        key = remote_path.lstrip("/")
        # Pod path /workspace/foo maps to S3 key foo.
        if key.startswith("workspace/"):
            key = key[len("workspace/"):]
        target = Path(local_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        def download() -> None:
            transferred = 0
            total = int(self._client.head_object(Bucket=self.volume_id, Key=key)["ContentLength"])

            def callback(amount: int) -> None:
                nonlocal transferred
                transferred += amount
                if on_progress:
                    on_progress(transferred, total)

            self._client.download_file(
                self.volume_id, str(PurePosixPath(key)), str(target), Callback=callback
            )

        await asyncio.to_thread(download)
