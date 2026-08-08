"""Real-engine validation: a 6hb with crossover extra bases survives oxDNA
relaxation AND a full production run.

Builds a seamless-autoscaffolded, fully-autostapled, fully-sequenced 6hb, adds
1–2 extra T bases at one specific crossover (precise) or at every crossover
(bulk), then drives the REAL CUDA oxDNA engine through the standard 3-stage
relaxation and an unbiased production stage at the code-default step counts.
Asserts the job reaches ``completed`` with the relaxed geometry recovered for
every real nucleotide and the designed duplex re-annealed (the extra ssDNA
inserts must not destabilise the relaxation).

Opt-in (a real relaxation + 5M-step production is ~minutes/GPU):
    NADOC_RUN_OXDNA_SLOW=1 just test-file tests/test_oxdna_extra_base_production.py
Needs a real oxDNA binary (``find_oxdna``) and a CUDA GPU.  Skipped otherwise.
"""

import os

import pytest

from backend.api import headless_build as hb
from backend.api import headless_oxdna_build as hox
from backend.api import state as design_state
from backend.core.models import LatticeType
from backend.core.oxdna_health import base_pair_retention
from backend.core.oxdna_job import OxdnaStatus
from backend.core.oxdna_runner import find_oxdna
from backend.physics import oxdna_interface as ox
from backend.physics.oxdna_interface import read_configuration_unwrapped

from tests.conftest import EIGHTEEN_HB_CELLS, SIX_HB_CELLS
from tests.test_oxdna_relaxation import _sequence_for_oxdna

# Code defaults (the user's "success" criterion for this validation).
PRODUCTION_STEPS = 5_000_000

# Designs routed + sequenced identically (seamless autoscaffold + full autostaple):
# a small 6hb and a larger, more crossover-dense 18hb — "ready for any design".
DESIGNS = {
    "6hb": (SIX_HB_CELLS, 84),  # ~1058 nt,  53 crossovers
    "18hb": (EIGHTEEN_HB_CELLS, 84),  # ~3210 nt, 185 crossovers
}


def _build_extra_base(design_key: str, mode: str):
    """A sequenced bundle with extra T bases added per *mode* ('precise' | 'bulk').
    Returns (design, expected_extra_nucleotides)."""
    cells, length = DESIGNS[design_key]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, length, lattice=LatticeType.HONEYCOMB, name=design_key)
        hb.auto_scaffold(seamless=True)
        hb.full_autostaple()
        design = design_state.get_or_404().model_copy(deep=True)
    design = _sequence_for_oxdna(design)

    if mode == "precise":
        design.crossovers[0].extra_bases = "TT"  # two extra bases at one junction
    elif mode == "bulk":
        for xo in design.crossovers:
            xo.extra_bases = "T"  # one extra base at every junction
    else:  # pragma: no cover
        raise ValueError(mode)

    expected = sum(
        len(extra)
        for _xo_id, extra in ox.crossover_extra_base_junctions(design).values()
    )
    assert expected > 0, "the variant must actually insert extra bases"
    return design, expected


def _assert_real_geometry_recovered(job, design, workspace, n_extra: int):
    """The relaxed last frame reads back a position for every REAL nucleotide
    (inserts occupy particle slots but drop from the design-keyed map) and the
    nucleotide count carries the extra bases."""
    order = ox._strand_nucleotide_order(design)
    real_keys = {k[:3] for k in order if k[0] != ox._XB_SENTINEL}
    assert sum(1 for k in order if k[0] == ox._XB_SENTINEL) == n_extra

    top = job.job_dir(workspace) / "topology.top"
    last = job.stage_dir(workspace, job.stages[-1].name) / "last_conf.dat"
    assert last.exists(), "no last_conf.dat from the final stage"

    full = read_configuration_unwrapped(last, design, top)
    assert not any(k[0] == ox._XB_SENTINEL for k in full), (
        "inserts must drop from read-back"
    )
    assert set(full.keys()) == real_keys, (
        "recovered geometry must cover every real nucleotide"
    )
    return full


@pytest.mark.slow
@pytest.mark.parametrize("design_key", ["6hb", "18hb"])
@pytest.mark.parametrize("mode", ["precise", "bulk"])
def test_extra_base_design_relaxes_and_runs_production(design_key, mode, tmp_path):
    if not os.environ.get("NADOC_RUN_OXDNA_SLOW"):
        pytest.skip(
            "opt-in: set NADOC_RUN_OXDNA_SLOW=1 (real relax + 5M production is ~minutes)"
        )
    if find_oxdna() is None:
        pytest.skip("no real oxDNA binary on PATH/$OXDNA_BIN")

    tag = f"{design_key}/{mode}"
    design, n_extra = _build_extra_base(design_key, mode)

    # Relaxation: standard 3-stage protocol at code defaults, real CUDA engine.
    job = hox.run_relaxation(
        design, tmp_path, backend="CUDA", timeout=3600.0, **hox.STANDARD_RELAX_PARAMS
    )
    assert job.status is OxdnaStatus.completed, (
        f"relaxation failed ({tag}): {job.error}"
    )

    full = _assert_real_geometry_recovered(job, design, tmp_path, n_extra)
    retention = base_pair_retention(design, full)[0]
    assert retention >= 0.85, (
        f"designed duplex did not re-anneal with extra bases ({tag}); "
        f"final retention {retention:.2f}"
    )

    # Production: unbiased MD at the code-default step count, continuing the trajectory.
    hox.append_production(job.job_id, tmp_path, steps=PRODUCTION_STEPS)
    job = hox.wait_for_terminal(job.job_id, tmp_path, timeout=7200.0)
    assert job.status is OxdnaStatus.completed, (
        f"production failed ({tag}): {job.error}"
    )
    assert any(s.kind == "production" for s in job.stages), "no production stage ran"

    # The relaxed geometry still reads back after production.
    _assert_real_geometry_recovered(job, design, tmp_path, n_extra)
