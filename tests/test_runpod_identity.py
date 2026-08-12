from backend.core.runpod_identity import installation_id, is_foreign_pod, pod_name, pod_owner


def test_pod_names_carry_the_local_installation_signature(monkeypatch):
    monkeypatch.setenv("NADOC_INSTANCE_ID", "desktop-a")
    installation_id.cache_clear()
    name = pod_name("design", "job123")
    assert name == "nadoc-i-desktopa-design-job123"
    assert pod_owner(name) == "desktopa"
    assert is_foreign_pod(name) is False

    monkeypatch.setenv("NADOC_INSTANCE_ID", "laptop-b")
    installation_id.cache_clear()
    assert is_foreign_pod(name) is True
    assert pod_owner("nadoc-old-style-job") is None
    installation_id.cache_clear()
