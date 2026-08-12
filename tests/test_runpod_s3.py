import json

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
