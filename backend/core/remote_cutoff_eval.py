"""Self-contained relaxation early-stop evaluator — runs on a bare cluster node.

This is the node-side half of the *in-sbatch* relaxation early-stop accelerator
(the CPU-cluster analogue of the local ``early_stop_relax`` path in
``namd_runner.run_job``).  A whole NADOC relaxation ladder runs as ONE sbatch on
Alpine (plan decision #1), with no Python runner in the loop; this script is the
one Python step the sbatch calls at each non-final relaxation chunk boundary to
decide whether that stage has plateaued and its remaining chunks can be skipped.

**CRITICAL — stdlib only.**  A copy of THIS FILE is staged into the job package and
executed on the compute node as ``python3 nadoc_cutoff_eval.py`` with NO NADOC
package on ``sys.path`` and (Tier B) NO third-party deps.  Therefore it must import
nothing from ``backend`` and (for the Tier-B energy path) nothing outside the
standard library.  The pure decision functions below are VENDORED VERBATIM from
``backend.core.md_cutoff`` and the frame parser from ``backend.core.namd_metrics``;
``tests/test_remote_cutoff_eval.py`` pins that the vendored copies stay in lockstep
with the originals (same thresholds, same decisions on the same data).

Exit-code contract (consumed by the sbatch ``if python3 …; then bridge; fi``):
  0  -> PLATEAU: skip the stage's remaining chunks (bridge the restart chain).
  1  -> HOLD:    not plateaued; run the remaining chunks normally.
  2  -> HOLD:    insufficient data / parse or usage error (fail safe = run).

Tier B (default): energy(+volume) plateau only, from the chunk's NAMD ``.log``.
Tier A (``--wc <json>``): additionally requires the WC base-pairing series (a JSON
list of per-frame fractions produced by an MDAnalysis health step) to be flat —
matching the local multi-criteria ``should_early_stop_stage`` exactly.
"""

# NB: NO `from __future__ import annotations` — Alpine compute nodes run an OLD
# system python3 (< 3.7, e.g. RHEL 3.6) after `module purge`, where that line is a
# hard SyntaxError (live-confirmed on amilan node c3cpu 2026-07-08). This file must
# parse+run on Python 3.6: keep new-generic annotations (list[str]) to LOCAL vars
# only (never evaluated) and use plain names in signatures / class fields.
import argparse
import json
import statistics as st
import sys

# ── VENDORED from backend.core.md_cutoff (keep in lockstep — see test) ─────────

# Plain class, NOT a @dataclass: the ``dataclasses`` module is Python 3.7+, and
# Alpine's bare node python3 is 3.6 (`ModuleNotFoundError: dataclasses`, live-
# confirmed on amilan c3cpu 2026-07-08). Class-level attributes give the same
# ``CutoffParams().field`` access with zero non-3.6 features.
class CutoffParams:
    """Thresholds separate DRIFT (has the mean settled? — the real convergence
    signal, kept tight) from FLUCT (instantaneous thermal noise — a loose "not
    exploding" guard).  Values kept in lockstep with ``md_cutoff.CutoffParams``."""

    window = 10             # trailing frames to test
    eps_pot_drift = 5e-4    # 0.05% mean drift = settled
    eps_pot_fluct = 3.5e-3  # 0.35% noise guard (fast-run thermal ~0.13%)
    eps_vol_drift = 3e-3    # 0.30% mean drift
    eps_vol_fluct = 5e-3    # 0.50% noise guard (fast-run thermal ~0.24%)
    eps_wc_drift = 0.02     # 2 pts mean drift
    eps_wc_fluct = 0.05     # 5 pts noise guard
    min_frames = 20         # skip a tiny p10 chunk; judge on p50's fuller series


def _series_flat(vals, window, drift_eps, fluct_eps, absolute):
    """True if the trailing ``window`` of ``vals`` has mean-drift < drift_eps AND
    scatter < fluct_eps.  Vendored verbatim from ``md_cutoff._series_flat``."""
    w = [v for v in vals[-window:] if v is not None]
    if len(w) < max(4, window // 2):
        return False
    lo, hi = w[: len(w) // 2], w[len(w) // 2:]
    drift = abs(st.mean(lo) - st.mean(hi))
    fluct = st.pstdev(w)
    if not absolute:
        scale = abs(st.mean(w)) or 1.0
        drift /= scale
        fluct /= scale
    return drift < drift_eps and fluct < fluct_eps


def energy_plateaued(frames, params=CutoffParams()):
    """POTENTIAL flat over the trailing window; VOLUME too when present (NPT).
    Vendored verbatim from ``md_cutoff.energy_plateaued``."""
    if len(frames) < params.min_frames:
        return False
    pot = [f.get("POTENTIAL") for f in frames]
    if not _series_flat(pot, params.window, params.eps_pot_drift,
                        params.eps_pot_fluct, absolute=False):
        return False
    vol = [f.get("VOLUME") for f in frames]
    if any(v is not None for v in vol):
        if not _series_flat(vol, params.window, params.eps_vol_drift,
                            params.eps_vol_fluct, absolute=False):
            return False
    return True


def wc_plateaued(wc_per_frame, params=CutoffParams()):
    """WC base-pairing flat over its trailing window.  Empty -> not proven -> False.
    Vendored verbatim from ``md_cutoff.wc_plateaued``."""
    if not wc_per_frame:
        return False
    return _series_flat(wc_per_frame, params.window, params.eps_wc_drift,
                        params.eps_wc_fluct, absolute=True)


def should_early_stop_stage(frames, wc_per_frame, params=CutoffParams()):
    """Decide whether the current stage has settled enough to skip its remaining
    chunks.  Requires BOTH energy and WC plateau.  Vendored verbatim from
    ``md_cutoff.should_early_stop_stage``."""
    e = energy_plateaued(frames, params)
    w = wc_plateaued(wc_per_frame, params)
    diag = {
        "n_energy_frames": len(frames),
        "n_wc_frames": len(wc_per_frame or []),
        "energy_plateaued": e,
        "wc_plateaued": w,
    }
    return (e and w), diag


# ── VENDORED from backend.core.namd_metrics.parse_namd_log_frames ──────────────


def parse_namd_log_frames(log_text):
    """Return EVERY ENERGY frame as a ``{column_name: value}`` dict.

    Vendored from ``namd_metrics.parse_namd_log_frames`` but takes the log TEXT
    (the node reads the file itself) rather than a path.  Restart-replayed duplicate
    frames at a resume seam (TS <= previous) are dropped so the series is monotone.
    """
    cols: list[str] = []
    out: list[dict] = []
    last_ts = None
    for line in log_text.splitlines():
        if line.startswith("ETITLE:"):
            cols = line.split()[1:]
        elif line.startswith("ENERGY:") and cols:
            vals = line.split()[1:]
            if len(vals) < len(cols):
                continue
            row: dict = {}
            for name, v in zip(cols, vals):
                try:
                    row[name] = float(v)
                except ValueError:
                    pass
            ts = row.get("TS")
            if last_ts is not None and ts is not None and ts <= last_ts:
                continue
            last_ts = ts
            out.append(row)
    return out


# ── CLI ────────────────────────────────────────────────────────────────────────

_EXIT_SKIP = 0   # plateau -> skip remaining chunks
_EXIT_HOLD = 1   # not plateaued -> run remaining chunks
_EXIT_ERR = 2    # insufficient data / error -> fail safe (run)


def decide(log_text, wc_per_frame=None, params=CutoffParams()):
    """(exit_code, diagnostics) for one chunk.  Tier B (wc None) = energy only;
    Tier A (wc list) = energy AND WC, i.e. ``should_early_stop_stage``."""
    frames = parse_namd_log_frames(log_text)
    if len(frames) < params.min_frames:
        return _EXIT_ERR, {"reason": "insufficient_frames", "n_energy_frames": len(frames)}
    if wc_per_frame is None:
        e = energy_plateaued(frames, params)
        diag = {"tier": "B", "n_energy_frames": len(frames), "energy_plateaued": e}
        return (_EXIT_SKIP if e else _EXIT_HOLD), diag
    decision, diag = should_early_stop_stage(frames, wc_per_frame, params)
    diag["tier"] = "A"
    return (_EXIT_SKIP if decision else _EXIT_HOLD), diag


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="NADOC relaxation early-stop plateau evaluator (node-side)."
    )
    ap.add_argument("--log", required=True, help="chunk NAMD .log path")
    ap.add_argument("--wc", default=None,
                    help="Tier A: JSON file with a list of per-frame WC fractions")
    args = ap.parse_args(argv)

    try:
        with open(args.log, encoding="utf-8", errors="replace") as fh:
            log_text = fh.read()
    except OSError as exc:
        print(f"[nadoc-cutoff] cannot read log {args.log}: {exc}", file=sys.stderr)
        return _EXIT_ERR

    wc = None
    if args.wc:
        try:
            with open(args.wc, encoding="utf-8") as fh:
                loaded = json.load(fh)
            wc = [float(x) for x in loaded]
        except (OSError, ValueError, TypeError) as exc:
            # Tier A requested but WC unreadable -> fail safe (hold), do not skip
            # on energy alone (that's exactly the unsafe case Tier A exists to avoid).
            print(f"[nadoc-cutoff] cannot read wc {args.wc}: {exc}", file=sys.stderr)
            return _EXIT_ERR

    code, diag = decide(log_text, wc)
    print(f"[nadoc-cutoff] {json.dumps(diag)}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
