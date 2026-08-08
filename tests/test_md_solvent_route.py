"""HTTP tests for the solvent / periodic-box routes (backend/api/routes_md).

The heavy MDAnalysis work is monkeypatched out — what is under test here is the
request contract, the binary content type, and the not-ready fallbacks. Real
extraction against a solvated PSF+DCD is the slow test.
"""

from __future__ import annotations

import json
import struct

import pytest
from fastapi.testclient import TestClient

import backend.api.routes_md as routes_md
from backend.api.main import app
from backend.core.md_solvent import SPECIES, empty_solvent_bin, pack_solvent_bin

client = TestClient(app)

URL = "/api/md/jobs/testjob/frames-solvent-bin"
MAGIC = 0x4E534C56


def _header(buf: bytes) -> dict:
    (header_len,) = struct.unpack_from("<I", buf, 16)
    return json.loads(buf[20:20 + header_len].decode("utf-8"))


@pytest.fixture
def canned(monkeypatch):
    """Capture the args the route hands the analysis runner; return a fixed blob."""
    seen: dict = {}

    async def _fake(request, job_id, kind, qualname, args, *, timeout_s=180.0):
        seen.update(job_id=job_id, kind=kind, qualname=qualname, args=args,
                    timeout_s=timeout_s)
        # Block sizes must agree with the header counts — pack_solvent_bin asserts
        # it, because a mismatch is what desynchronises the client's reader.
        return pack_solvent_bin({0: {
            "water": [1.0, 2.0, 3.0], "ions": [], "box": [0.0] * 24,
            "n_water": 1, "n_ions": 0, "n_ions_total": 4, "n_waters_total": 10,
            "has_box": True, "atomistic": False, "capped": False, "shell_nm": 0.5,
        }})

    monkeypatch.setattr(routes_md, "_run_md_analysis", _fake)
    monkeypatch.setattr(routes_md, "_md_traj_inputs",
                        lambda job_id: ("psf", "ref", [("s", 0, "a.dcd")], "design"))
    return seen


class TestFramesSolventRoute:
    def test_returns_an_octet_stream_with_the_right_magic(self, canned):
        r = client.post(URL, json={"frame_indices": [0]})
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/octet-stream"
        assert struct.unpack_from("<I", r.content, 0)[0] == MAGIC

    def test_dispatches_to_the_solvent_orchestrator_under_its_own_cancel_kind(self, canned):
        client.post(URL, json={"frame_indices": [0, 1]})
        assert canned["qualname"] == "md_frames_solvent"
        # A distinct kind, so toggling solvent off cannot cancel the trajectory read.
        assert canned["kind"] == "solvent"

    def test_defaults_match_the_documented_contract(self, canned):
        client.post(URL, json={"frame_indices": [0]})
        opts = canned["args"][-1]
        assert opts == {"water": True, "ions": True, "box": True,
                        "shell_ang": 5.0, "atomistic": False,
                        "max_waters": None, "include_dna": False}

    def test_body_fields_reach_the_orchestrator(self, canned):
        client.post(URL, json={"frame_indices": [3], "water": False, "ions": True,
                               "box": False, "shell_ang": 8.0, "atomistic": True,
                               "max_waters": 1000, "include_dna": True})
        opts = canned["args"][-1]
        assert opts["shell_ang"] == 8.0
        assert opts["atomistic"] is True
        assert opts["max_waters"] == 1000
        assert opts["include_dna"] is True
        assert opts["water"] is False and opts["box"] is False

    # None is "the whole cell", which is a different request from "5 A" — it has to
    # survive Pydantic rather than being coerced to the default.
    def test_null_shell_means_the_whole_box(self, canned):
        client.post(URL, json={"frame_indices": [0], "shell_ang": None})
        assert canned["args"][-1]["shell_ang"] is None

    def test_stride_is_forwarded_positionally_before_the_opts(self, canned):
        client.post(URL, json={"frame_indices": [0], "stride": 20})
        # (psf, segments, ref, design, frame_indices, max_frames, stride, opts)
        assert canned["args"][6] == 20
        assert isinstance(canned["args"][-1], dict)

    def test_timeout_scales_with_the_frame_count(self, canned):
        client.post(URL, json={"frame_indices": [0]})
        one = canned["timeout_s"]
        client.post(URL, json={"frame_indices": list(range(32))})
        assert canned["timeout_s"] > one
        assert canned["timeout_s"] <= 3600.0

    def test_frame_indices_are_required(self, canned):
        assert client.post(URL, json={}).status_code == 422


class TestNotReady:
    def test_missing_topology_yields_the_empty_payload_not_an_error(self, monkeypatch):
        monkeypatch.setattr(routes_md, "_md_traj_inputs", lambda job_id: None)
        r = client.post(URL, json={"frame_indices": [0]})
        assert r.status_code == 200
        assert r.content == empty_solvent_bin()
        assert _header(r.content)["frame_ids"] == []

    def test_a_non_bytes_result_degrades_to_the_empty_payload(self, monkeypatch):
        async def _fake(request, job_id, kind, qualname, args, *, timeout_s=180.0):
            return None            # cancelled / superseded analysis

        monkeypatch.setattr(routes_md, "_run_md_analysis", _fake)
        monkeypatch.setattr(routes_md, "_md_traj_inputs",
                            lambda job_id: ("psf", "ref", [("s", 0, "a.dcd")], "d"))
        r = client.post(URL, json={"frame_indices": [0]})
        assert r.status_code == 200
        assert r.content == empty_solvent_bin()


class TestSolventMeta:
    """Answered from two small JSON files — no MDAnalysis, no trajectory read."""

    def _job(self, monkeypatch, tmp_path, audit=None, manifest=None):
        pkg = tmp_path / "package"
        pkg.mkdir(parents=True, exist_ok=True)
        if audit is not None:
            (pkg / "charge_audit.json").write_text(json.dumps(audit))
        if manifest is not None:
            (pkg / "manifest.json").write_text(json.dumps(manifest))

        class _Job:
            def package_dir(self, ws):
                return pkg

        monkeypatch.setattr(routes_md, "_load_job", lambda job_id: _Job())
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)

    def test_reports_counts_from_the_charge_audit(self, monkeypatch, tmp_path):
        self._job(monkeypatch, tmp_path, audit={"ionization": {
            "n_na": 948, "n_cl": 38, "n_mg": 19, "n_waters": 69574,
            "mg_hexahydrate": True, "box_nm": [12.209, 8.912, 22.678]}})
        body = client.get("/api/md/jobs/testjob/solvent-meta").json()
        assert body["ready"] is True
        assert body["n_ions"] == 948 + 38 + 19
        assert body["species"] == {"NA": 948, "CL": 38, "MG": 19}
        assert body["box_nm"] == [12.209, 8.912, 22.678]

    # The audit counts BULK water; the viewer also draws the six waters of every
    # magnesium hexahydrate, so the drawable count is n_waters + 6*n_mg. Verified
    # against the real 10hb package: 69574 + 6*19 == 69688 oxygens found by
    # build_solvent_ctx.
    def test_hexahydrate_waters_are_counted_as_drawable_water(self, monkeypatch, tmp_path):
        self._job(monkeypatch, tmp_path, audit={"ionization": {
            "n_na": 948, "n_cl": 38, "n_mg": 19, "n_waters": 69574,
            "mg_hexahydrate": True}})
        body = client.get("/api/md/jobs/testjob/solvent-meta").json()
        assert body["n_waters"] == 69688
        assert body["mg_hexahydrate"] is True

    def test_no_hexahydrate_means_no_extra_water(self, monkeypatch, tmp_path):
        self._job(monkeypatch, tmp_path, audit={"ionization": {
            "n_na": 10, "n_cl": 10, "n_mg": 5, "n_waters": 100,
            "mg_hexahydrate": False}})
        assert client.get("/api/md/jobs/testjob/solvent-meta").json()["n_waters"] == 100

    def test_box_falls_back_to_the_manifest(self, monkeypatch, tmp_path):
        self._job(monkeypatch, tmp_path,
                  audit={"ionization": {"n_na": 1, "n_cl": 1, "n_mg": 0, "n_waters": 5}},
                  manifest={"box_ang": [122.09, 89.119, 226.78]})
        body = client.get("/api/md/jobs/testjob/solvent-meta").json()
        assert body["box_nm"] == pytest.approx([12.209, 8.9119, 22.678])

    def test_a_package_with_no_audit_reports_not_ready(self, monkeypatch, tmp_path):
        self._job(monkeypatch, tmp_path)
        body = client.get("/api/md/jobs/testjob/solvent-meta").json()
        assert body["ready"] is False
        assert body["n_waters"] == 0 and body["n_ions"] == 0

    # Replica packages hardlink only the immutable structure files, and some builders
    # fold the audit into the manifest instead of writing a standalone file. Reading
    # only charge_audit.json made those jobs report zero of everything, so the panel
    # printed "no ions in this job" over a cell the renderer was filling with Mg2+
    # straight out of the PSF. Measured from the live 6hbx100_noT production package.
    def test_audit_falls_back_to_the_manifest(self, monkeypatch, tmp_path):
        self._job(monkeypatch, tmp_path, manifest={
            "box_ang": [83.121, 89.119, 436.906],
            "charge_audit": {"ionization": {
                "n_na": 1307, "n_cl": 48, "n_mg": 24, "n_waters": 89973,
                "mg_hexahydrate": True}}})
        body = client.get("/api/md/jobs/testjob/solvent-meta").json()
        assert body["ready"] is True
        assert body["species"] == {"NA": 1307, "CL": 48, "MG": 24}
        assert body["n_ions"] == 1307 + 48 + 24
        assert body["n_waters"] == 89973 + 6 * 24
        assert body["box_nm"] == pytest.approx([8.3121, 8.9119, 43.6906])

    # A standalone file and a manifest copy can both be present; the file is the one
    # written by THIS package's solvation run, so it wins.
    def test_the_standalone_audit_wins_over_the_manifest(self, monkeypatch, tmp_path):
        self._job(monkeypatch, tmp_path,
                  audit={"ionization": {"n_na": 5, "n_cl": 5, "n_mg": 0, "n_waters": 9}},
                  manifest={"charge_audit": {"ionization": {
                      "n_na": 999, "n_cl": 0, "n_mg": 0, "n_waters": 0}}})
        body = client.get("/api/md/jobs/testjob/solvent-meta").json()
        assert body["species"] == {"NA": 5, "CL": 5, "MG": 0}

    def test_a_corrupt_audit_does_not_raise(self, monkeypatch, tmp_path):
        pkg = tmp_path / "package"
        pkg.mkdir(parents=True)
        (pkg / "charge_audit.json").write_text("{not json")

        class _Job:
            def package_dir(self, ws):
                return pkg

        monkeypatch.setattr(routes_md, "_load_job", lambda job_id: _Job())
        monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
        assert client.get("/api/md/jobs/testjob/solvent-meta").status_code == 200


def test_cancel_accepts_the_solvent_kind(monkeypatch):
    seen = {}
    from backend.core import md_analysis_runner

    monkeypatch.setattr(md_analysis_runner, "cancel",
                        lambda job_id, kind: seen.setdefault("kind", kind) or True)
    r = client.post("/api/md/jobs/testjob/analysis/cancel?kind=solvent")
    assert r.status_code == 200
    assert seen["kind"] == "solvent"


def test_species_table_is_exposed_to_the_client():
    """The frontend maps species CODE → colour, so the table must ride the wire."""
    assert _header(empty_solvent_bin())["species_table"] == list(SPECIES)
