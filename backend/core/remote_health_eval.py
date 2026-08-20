"""Node health step — per-frame WC base-pairing for one relaxation chunk.

The node-side companion to ``remote_cutoff_eval.py`` for the in-sbatch early-stop
path.  It computes the chunk's ``wc_per_frame`` series (the same one the local
runner feeds to ``md_cutoff.should_early_stop_stage``) and writes it as a JSON list
that ``nadoc_cutoff_eval.py --wc`` consumes — required on every eligible chunk, no
energy-only fallback.

REQUIRES numpy + scipy + MDAnalysis on the node python.  It runs the ACTUAL
``md_health.run_health_check`` (a verbatim copy of ``backend.core.md_health`` is
staged next to this file — as of 2026-08-21 that copy is self-contained, with no
further ``backend`` import, so its ss-exclusion logic runs correctly standalone; see
[[project_declash_reaudit]]), so the remote WC metric is byte-for-byte the local
one; ``run_health_check`` reads only the staged ``{stem}.psf``/``.pdb`` and the
freshly written ``output/{seg}.dcd`` (all present on the node).

Fails safe: on ANY problem (missing MDAnalysis, no frames yet, read error) it writes
nothing and exits non-zero, so the sbatch's ``[ -f wc.json ] && cutoff --wc`` gate
falls through to HOLD — this never skips on energy alone (that is exactly the
unsafe case the WC step exists to prevent).
"""

# NB: NO `from __future__ import annotations` — see remote_cutoff_eval.py; Alpine's
# bare node python3 is < 3.7 and SyntaxErrors on it (live-confirmed 2026-07-08). The
# WC (MDAnalysis) step still needs a MODERN python (>=3.9) via early_stop_health_python
# + a `module load`; this file itself must at least PARSE on the old python so its
# failure is a clean ImportError, not a SyntaxError that never runs.
import argparse
import json
import sys
from pathlib import Path

_EXIT_OK = 0
_EXIT_NO_WC = 3  # no usable WC series -> caller holds (fail safe)


def _load_md_health():
    """Import the staged sibling ``md_health`` on the node; fall back to the backend
    package when running inside the repo (unit tests, local dev)."""
    try:
        import md_health  # staged copy sits next to this file on the node

        return md_health
    except ImportError:
        from backend.core import md_health  # type: ignore

        return md_health


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Tier-A node WC health step for relaxation early-stop."
    )
    ap.add_argument(
        "--package-dir", default=".", help="run cwd holding {stem}.psf/.pdb + output/"
    )
    ap.add_argument(
        "--seg", required=True, help="chunk output name (expects output/<seg>.dcd)"
    )
    ap.add_argument("--stem", required=True, help="structure name stem")
    ap.add_argument(
        "--out", required=True, help="where to write the wc_per_frame JSON list"
    )
    args = ap.parse_args(argv)

    try:
        md_health = _load_md_health()
        res = md_health.run_health_check(Path(args.package_dir), args.seg, args.stem)
        wc = [float(x) for x in (res.wc_per_frame or [])]
    except Exception as exc:  # noqa: BLE001 — fail safe to HOLD
        print(f"[nadoc-health] {type(exc).__name__}: {exc}", file=sys.stderr)
        return _EXIT_NO_WC
    if not wc:
        print(
            "[nadoc-health] no wc_per_frame (no frames yet / read error)",
            file=sys.stderr,
        )
        return _EXIT_NO_WC
    Path(args.out).write_text(json.dumps(wc))
    print(f"[nadoc-health] wrote {len(wc)} wc frames -> {args.out}", file=sys.stderr)
    return _EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
