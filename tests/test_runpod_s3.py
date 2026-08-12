import json
import asyncio

from backend.core import runpod_s3


def test_endpoint_uses_documented_datacenter_shape():
    assert runpod_s3.endpoint_for("EU-RO-1") == "https://s3api-eu-ro-1.runpod.io/"


def test_credentials_are_saved_owner_only_and_resolved(tmp_path, monkeypatch):
    path = tmp_path / "runpod_s3.json"
    monkeypatch.setattr(runpod_s3, "credentials_path", lambda: path)
    monkeypatch.delenv("RUNPOD_S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("RUNPOD_S3_SECRET_KEY", raising=False)
    runpod_s3.save_credentials("user_test", "rps_secret")
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["secret_key"] == "rps_secret"
    assert runpod_s3.resolve_credentials().source == "file"


def test_environment_credentials_take_priority(monkeypatch):
    monkeypatch.setenv("RUNPOD_S3_ACCESS_KEY", "user_env")
    monkeypatch.setenv("RUNPOD_S3_SECRET_KEY", "rps_env")
    assert runpod_s3.resolve_credentials() == runpod_s3.S3Credentials("user_env", "rps_env", "env")


def test_s3_connection_maps_pod_workspace_to_volume_root(monkeypatch):
    class FakeBoto:
        def client(self, *_args, **_kwargs):
            return object()

    monkeypatch.setattr("boto3.client", FakeBoto().client)
    conn = runpod_s3.RunpodS3Connection(
        runpod_s3.S3Credentials("user_x", "rps_x", "test"),
        volume_id="vol", data_center_id="EU-RO-1",
        remote_root="/workspace/nadoc_jobs/job1",
    )
    assert conn.remote_root == "nadoc_jobs/job1"


def test_s3_upload_is_multipart_parallel_and_maps_workspace_key(tmp_path, monkeypatch):
    source = tmp_path / "package.tar.gz"
    source.write_bytes(b"x" * 100)
    seen = {}

    class Client:
        def upload_file(self, filename, bucket, key, Callback=None, Config=None):
            seen.update(filename=filename, bucket=bucket, key=key, config=Config)
            Callback(40)
            Callback(60)

    monkeypatch.setattr("boto3.client", lambda *_a, **_kw: Client())
    conn = runpod_s3.RunpodS3Connection(
        runpod_s3.S3Credentials("user_x", "rps_x", "test"),
        volume_id="vol", data_center_id="EU-RO-1", remote_root="/workspace/job",
    )
    progress = []
    asyncio.run(conn.sftp_put(
        str(source), "/workspace/nadoc_jobs/j/.nadoc_stage/package.tar.gz",
        on_progress=lambda done, total: progress.append((done, total)),
    ))
    # call_soon_threadsafe callbacks drain before to_thread returns to the coroutine.
    assert progress[-1] == (100, 100)
    assert seen["key"] == "nadoc_jobs/j/.nadoc_stage/package.tar.gz"
    assert seen["config"].max_concurrency == 10
    assert seen["config"].multipart_chunksize == 16 * 1024 * 1024


def test_s3_file_inventory_is_relative_to_job_root(monkeypatch):
    class Pages:
        def paginate(self, **_kwargs):
            return [{"Contents": [
                {"Key": "nadoc_jobs/j/a.psf", "Size": 12},
                {"Key": "nadoc_jobs/j/forcefield/x.prm", "Size": 34},
            ]}]

    class Client:
        def get_paginator(self, _name):
            return Pages()

    monkeypatch.setattr("boto3.client", lambda *_a, **_kw: Client())
    conn = runpod_s3.RunpodS3Connection(
        runpod_s3.S3Credentials("user_x", "rps_x", "test"),
        volume_id="vol", data_center_id="EU-RO-1",
        remote_root="/workspace/nadoc_jobs/j",
    )
    assert asyncio.run(conn.file_sizes()) == {"a.psf": 12, "forcefield/x.prm": 34}
