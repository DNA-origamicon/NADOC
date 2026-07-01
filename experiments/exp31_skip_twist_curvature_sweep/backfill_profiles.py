"""Back-fill twist-vs-position profiles for runs that completed BEFORE profiling was wired in.

Reads each completed run's pooled mean (archive-aware — `job_dir()` resolves to the archive
drive via the index), recomputes the ~24-bp cumulative twist profile, and writes its CSV + PNG
into results/profiles/.  Idempotent; safe to re-run.  Future runs get this automatically from
run.py.  Usage:  python backfill_profiles.py
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import profile as P  # noqa: E402

from backend.api.headless_oxdna_build import read_flexibility_map  # noqa: E402
from backend.api.skip_twist_tuning import core_reference_geometry  # noqa: E402
from backend.core.oxdna_health import _filter_to_reference_core  # noqa: E402
from backend.core.oxdna_job import OxdnaJob  # noqa: E402
from backend.core.oxdna_runner import _load_snapshot_design  # noqa: E402

WS = HERE / "ws"
PROF = HERE / "results" / "profiles"
LENGTH_BP = 400


def main() -> None:
    recs = json.loads((HERE / "results" / "results.json").read_text())
    seen: set[str] = set()
    for r in recs:
        if r.get("status") != "ok":
            continue
        jid = r["job_id"]
        if jid in seen:                       # one profile per distinct sim (skip baseline mirrors)
            continue
        seen.add(jid)
        label = P.run_label(r["strategy"], r["delta"])
        try:
            job = OxdnaJob.load(jid, WS)
            design = _load_snapshot_design(job.job_dir(WS))
            mean = read_flexibility_map(jid, WS)
            ref = core_reference_geometry(design)
            core = _filter_to_reference_core(mean["positions"], ref)
            prof = P.compute_twist_profile(core, ref, length_bp=LENGTH_BP)
            P.save_profile_csv(prof, PROF / f"{label}.csv")   # combined PNG (plot.py) reads the CSVs
            print(f"{label}: {len(prof)} bins, endpoint {prof[-1]['cum_twist_diff']:.1f}° "
                  f"→ profiles/{label}.csv", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"{label}: FAILED — {e}", flush=True)
    print("backfill done.")


if __name__ == "__main__":
    main()
