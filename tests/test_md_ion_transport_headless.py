import asyncio

import backend.api.routes_md as routes_md


def test_headless_prepare_lowers_to_gpu_runpod_relax(monkeypatch):
    seen = {}

    async def fake_create(body):
        seen["body"] = body
        return {"job_id": "relax1", "status": "preparing"}

    monkeypatch.setattr(routes_md, "create_md_job", fake_create)
    out = asyncio.run(routes_md.prepare_headless_ion_transport(
        routes_md.HeadlessIonTransportPrepareRequest(
            oxdna_job_id="ox1", runpod_budget_usd=5.0,
        )
    ))
    body = seen["body"]
    assert body.graphene_nanopore is True
    assert body.gpu_resident == "on" and body.devices == "0"
    assert body.execution_target == "runpod" and body.runpod_budget_usd == 5.0
    assert out["next"].endswith("/relax1/run")


def test_headless_prepare_supports_graphene_only_control(monkeypatch):
    seen = {}

    async def fake_create(body):
        seen["body"] = body
        return {"job_id": "graphene1", "status": "preparing"}

    monkeypatch.setattr(routes_md, "create_md_job", fake_create)
    out = asyncio.run(routes_md.prepare_headless_ion_transport(
        routes_md.HeadlessIonTransportPrepareRequest(
            graphene_only=True, pore_diameter_nm=2.1,
            reservoir_padding_nm=3.5, execution_target="local", autostart=False,
        )
    ))
    body = seen["body"]
    assert body.oxdna_job_id is None
    assert body.graphene_only is True and body.graphene_nanopore is True
    assert body.padding_nm == 3.5
    assert body.salt_mode == "custom" and body.ion_conc_mM == 150
    assert out["next"].endswith("/graphene1/run")


def test_headless_prepare_requires_seed_or_graphene_only():
    import pytest
    with pytest.raises(Exception) as exc:
        asyncio.run(routes_md.prepare_headless_ion_transport(
            routes_md.HeadlessIonTransportPrepareRequest()
        ))
    assert getattr(exc.value, "status_code", None) == 400


def test_headless_run_lowers_to_voltage_transport(monkeypatch):
    seen = {}

    async def fake_spawn(parent, body):
        seen.update(parent=parent, body=body)
        return {"ok": True}

    monkeypatch.setattr(routes_md, "_spawn_md_production_impl", fake_spawn)
    asyncio.run(routes_md.run_headless_ion_transport(
        "relax1",
        routes_md.HeadlessIonTransportRunRequest(
            length_ns=2, voltage_mV=-150, current_stride_ps=10,
        ),
    ))
    body = seen["body"]
    assert seen["parent"] == "relax1"
    assert body.ion_transport_mode == "voltage"
    assert body.ion_transport_voltage_mV == -150
    assert body.gpu_resident == "on" and body.production_timestep_fs == 4
    assert body.dcd_freq == 2500 and body.runpod_budget_usd == 5.0
