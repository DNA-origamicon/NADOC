"""Every protocol's ``prepare_*`` must accept the ONE kwarg set the prep call site sends.

``routes_md`` prepares every protocol through a single ``run_in_threadpool(prepare, ...)``
call with a uniform keyword set, and each protocol's entry point is expected to
accept-and-ignore whatever does not apply to it.  Nothing enforced that, so when the
GPU-resident dropdown added ``gpu_resident_mode`` to the call site (commit 8823377,
2026-07-28) and did not add it to ``prepare_implicit_gbis_namd``, EVERY implicit-solvent
job began failing at prep with::

    Preparation failed: prepare_implicit_gbis_namd() got an unexpected keyword argument
    'gpu_resident_mode'

The failure is invisible to type checking and to every existing test, because the call is
dynamic (``prepare`` is bound to one of three functions) and the kwargs are literal.  This
test reads the call site with ``ast`` and checks each candidate function against it, so
adding a kwarg without updating a protocol fails here instead of in a user's job.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

ROUTES = Path(__file__).resolve().parents[1] / "backend" / "api" / "routes_md.py"


def _prep_call_kwargs() -> set[str]:
    """Keyword names passed to ``run_in_threadpool(prepare, ...)`` in routes_md."""
    tree = ast.parse(ROUTES.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name != "run_in_threadpool":
            continue
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Name) and first.id == "prepare":
            return {kw.arg for kw in node.keywords if kw.arg is not None}
    raise AssertionError(
        "could not find run_in_threadpool(prepare, ...) in routes_md — if that call was "
        "renamed or restructured, update this test rather than deleting it"
    )


def _accepts(fn, names: set[str]) -> set[str]:
    """Names ``fn`` cannot accept as keywords (empty set when it takes **kwargs)."""
    sig = inspect.signature(fn)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return set()
    ok = {
        n
        for n, p in sig.parameters.items()
        if p.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return names - ok


def _prepare_functions() -> dict:
    from backend.core.md_protocols import (
        prepare_equilibrium_aware_namd,
        prepare_mgh_slow_release,
    )
    from backend.core.namd_gbis import prepare_implicit_gbis_namd

    return {
        "equilibrium_aware_namd": prepare_equilibrium_aware_namd,
        "mgh_slow_release": prepare_mgh_slow_release,
        "implicit_gbis_namd": prepare_implicit_gbis_namd,
    }


def test_the_call_site_is_still_findable_and_nonempty():
    kwargs = _prep_call_kwargs()
    assert "progress" in kwargs and "minimize_steps" in kwargs
    assert len(kwargs) >= 10


@pytest.mark.parametrize("protocol", sorted(_prepare_functions()))
def test_every_protocol_accepts_every_prep_kwarg(protocol):
    fn = _prepare_functions()[protocol]
    missing = _accepts(fn, _prep_call_kwargs())
    assert not missing, (
        f"{fn.__name__} cannot accept {sorted(missing)} — routes_md passes one uniform "
        f"kwarg set to every protocol, so each entry point must accept-and-ignore what "
        f"does not apply to it"
    )


def test_gbis_accepts_the_two_kwargs_that_actually_broke_it():
    """Named explicitly so the regression is legible without re-deriving it."""
    from backend.core.namd_gbis import prepare_implicit_gbis_namd

    params = inspect.signature(prepare_implicit_gbis_namd).parameters
    assert "gpu_resident_mode" in params
    assert "production_timestep_fs" in params


def test_the_seed_kwargs_branch_stays_protocol_aware():
    """The piercing override and ``require_full_topology`` are added conditionally
    because GBIS has neither; if that guard is dropped, GBIS breaks the same way."""
    src = ROUTES.read_text()
    assert "if body.protocol != IMPLICIT_GBIS_PROTOCOL:" in src
    assert 'seed_kwargs["allow_ring_pierced_seed"]' in src


def test_oxdna_seed_forces_conservative_declash_ladder():
    """A CG seed cannot enter rigid/HMR dynamics before atomistic declashing."""
    src = ROUTES.read_text()
    assert "declash=True if body.oxdna_job_id else body.declash" in src
    assert "force_soft=bool(body.force_soft or body.oxdna_job_id)" in src
