"""Seed a completed oxDNA job + a matching .nadoc for the AF-26 end-to-end test.

GPU-free: we do NOT run a relaxation. We build a routed+sequenced 6hb, write it as
a .nadoc the browser tab will load, then drop a COMPLETED job into the workspace whose
``design_fingerprint`` / ``feature_log_position`` match that design's RE-IMPORTED state
(import applies migrate/backfill, so the fingerprint must be taken after a round-trip to
match what the tab actually loads).  We also emit one VALID overhang placement (computed
on the re-imported design, so its helix ids match the tab's) for the edit the test makes.

Output (stdout, last line): JSON ``{job_id, nadoc_path, run_position, overhang:{...}}``.

Run: ``uv run python tests/e2e_seed_af26.py [workspace_dir]``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.lattice import overhang_candidate_error
from backend.core.models import LatticeType
from backend.core.oxdna_job import OxdnaStatus, new_oxdna_job
from backend.core.oxdna_staleness import (
    effective_feature_log_position,
    oxdna_design_fingerprint,
)
from tests.automation_harness import roundtrip_nadoc
from tests.conftest import SIX_HB_CELLS
from tests.test_headless_build import _hc_neighbors, _staple_termini


def _find_overhang(design):
    """A valid (helix_id, bp, direction, is_five_prime, neighbor) overhang site."""
    hobj = {h.id: h for h in design.helices}
    occ = {h.grid_pos for h in design.helices}
    for hid, bp, dirn, is5 in _staple_termini(design):
        r, c = hobj[hid].grid_pos
        for nr, nc in _hc_neighbors(r, c):
            if (nr, nc) in occ:
                continue
            if overhang_candidate_error(design, hobj[hid], bp, dirn, nr, nc) is None:
                return {
                    "helixId": hid,
                    "bpIndex": bp,
                    "direction": str(dirn.value if hasattr(dirn, "value") else dirn),
                    "isFivePrime": bool(is5),
                    "neighborRow": nr,
                    "neighborCol": nc,
                    "lengthBp": 8,
                }
    raise SystemExit("no valid overhang candidate on the seeded 6hb")


# A marker design_name so prior seed jobs are identifiable + self-cleaned (keeps the
# real workspace from accumulating one throwaway job per e2e run).
_SEED_NAME = "af26-e2e-seed"


def _purge_old_seeds(workspace: Path) -> None:
    import json as _json
    import shutil

    jobs_dir = workspace / "oxdna_jobs"
    if not jobs_dir.exists():
        return
    for jdir in jobs_dir.iterdir():
        jf = jdir / "job.json"
        if not jf.exists():
            continue
        try:
            d = _json.loads(jf.read_text())
        except Exception:
            continue
        # Purge our own throwaway seeds only: the marker name, OR the unmistakable
        # seed signature (a fingerprinted job with NO stages and NO source path —
        # a real relaxation always has stages). Never touches a genuine run.
        is_marker = d.get("design_name") == _SEED_NAME
        is_legacy_seed = (
            d.get("design_name") == "6hb"
            and not d.get("stages")
            and d.get("design_fingerprint")
            and not d.get("design_source_path")
        )
        if is_marker or is_legacy_seed:
            shutil.rmtree(jdir, ignore_errors=True)


def main() -> None:
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else "workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    _purge_old_seeds(workspace)

    # Build a routed, broken, sequenced 6hb in an isolated scratch session.
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        hb.assign_scaffold_sequence()
        hb.assign_staple_sequences()
        built = design_state.get_or_404().model_copy(deep=True)

    nadoc_text = built.to_json()
    nadoc_path = (workspace / "af26_e2e.nadoc").resolve()
    nadoc_path.write_text(nadoc_text)

    # The tab loads via /design/import (migrate/backfill) — take the fingerprint
    # + overhang site from the RE-IMPORTED design so they match the tab's state.
    reimported = roundtrip_nadoc(built)
    run_fp = oxdna_design_fingerprint(reimported)
    run_pos = effective_feature_log_position(reimported)
    overhang = _find_overhang(reimported)

    # A completed mock job relaxed at the run state.
    job = new_oxdna_job(
        _SEED_NAME, [], design_fingerprint=run_fp, feature_log_position=run_pos
    )
    job.status = OxdnaStatus.completed
    job.save(workspace)
    (job.job_dir(workspace) / "design.json").write_text(reimported.model_dump_json())

    print(
        json.dumps(
            {
                "job_id": job.job_id,
                "nadoc_path": str(nadoc_path),
                "run_position": run_pos,
                "overhang": overhang,
            }
        )
    )


if __name__ == "__main__":
    main()
