"""Self-contained cell-shrink resume-conf writer — runs ON the rented pod.

**CRITICAL — stdlib only.** A copy of THIS FILE is staged into the job package and run as
``python3 nadoc_resume_conf.py`` with no NADOC package on ``sys.path``. It must import
nothing from ``backend``.

## Why this exists

An NPT box relaxes ~3% to equilibrium density and crosses NAMD's fixed patch grid:

    FATAL ERROR: Periodic cell has become too small for original patch grid!

That is NOT a blow-up (T/P/energy stay healthy) and it IS self-healing — but ONLY if the
restart rebuilds the grid at the SMALLER box. The RunPod chain script's retry used to
simply re-run the original conf, which reads

    extendedSystem  output/<minimisation>.xsc      <-- the ORIGINAL cell

so NAMD rebuilt the SAME patch grid, the box shrank into the SAME wall, and all four
retries failed identically. Measured on the live 3x6x400 pod:

    conf (original) : 156.636 x  89.136 x 1436.190
    restart @ 4000  : 151.972 x  86.482 x 1393.426     (-3.0% on every axis)

Resuming from the segment's OWN ``output/<seg>.restart.{coor,vel,xsc}`` picks up the
shrunken cell, so the grid is sized correctly and the segment proceeds. This is the
pod-side equivalent of the local runner's ``_write_resume_conf``.

## One deliberate difference from md_protocols.build_remote_resume_conf

That one writes the continuation trajectory to ``output/<seg>.cont<k>.dcd`` to preserve the
partial. We write to ``output/<seg>.dcd`` — OVERWRITING it — on purpose:

  * Tier-A early-stop reads its WC base-pairing series off ``output/<seg>.dcd``. If the
    continuation went to a different file, that series would contain only the handful of
    PRE-shrink frames, fall under the evaluator's window, and report HOLD forever — the
    segment would silently lose its ability to bridge.
  * The discarded frames are the box equilibrating at a cell that NAMD has just declared
    invalid. They are not physics anyone wants.
"""

# NB: no `from __future__ import annotations` and no dataclasses — this must parse on an
# old system python, same constraint as remote_cutoff_eval.py.
import argparse
import sys

# VENDORED from backend.core.md_protocols._RESUME_DROP (kept in lockstep by
# tests/test_remote_resume_conf.py). Directives the resume conf must re-emit itself.
_RESUME_DROP = frozenset([
    "binCoordinates", "binVelocities", "extendedSystem", "temperature",
    "reinitvels", "firsttimestep", "dcdFile", "xstFile", "run",
])


def restart_step_of(xsc_text):
    """The step number NAMD checkpointed at — the first field of the last data line.

    An .xsc is a comment header (`#`-prefixed) plus one line per write, each beginning
    with the step. The LAST one is the newest checkpoint.
    """
    for line in reversed(xsc_text.strip().splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return int(float(line.split()[0]))
    raise ValueError("no data line in the .xsc — cannot tell where to resume from")


def build_resume_conf(conf_text, segment_name, restart_step, total_steps):
    """Drop the directives that pin the original start, re-emit them at the checkpoint."""
    remaining = int(total_steps) - int(restart_step)
    if remaining <= 0:
        raise ValueError(
            "resume step %d is at/past the segment total %d" % (restart_step, total_steps)
        )
    kept = [
        line for line in conf_text.splitlines()
        if (line.split()[0] if line.split() else "") not in _RESUME_DROP
    ]
    kept += [
        "binCoordinates     output/%s.restart.coor" % segment_name,
        "binVelocities      output/%s.restart.vel" % segment_name,
        # THE fix: the shrunken cell. Supersedes any cellBasisVector still in the conf.
        "extendedSystem     output/%s.restart.xsc" % segment_name,
        "dcdFile            output/%s.dcd" % segment_name,
        "xstFile            output/%s.xst" % segment_name,
        "firsttimestep      %d" % int(restart_step),
        # NAMD 3's Tcl `run` has no `upto`; firsttimestep already advanced the label, so
        # run only what is left. restart_step is a multiple of restartfreq (itself a
        # multiple of stepspercycle), so the remainder stays cycle-aligned.
        "run                %d" % remaining,
    ]
    return "\n".join(kept) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="write <seg>.resume.conf from a checkpoint")
    ap.add_argument("--seg", required=True)
    ap.add_argument("--total-steps", required=True, type=int)
    args = ap.parse_args(argv)

    try:
        with open("output/%s.restart.xsc" % args.seg) as fh:
            step = restart_step_of(fh.read())
        with open("%s.conf" % args.seg) as fh:
            conf = fh.read()
        text = build_resume_conf(conf, args.seg, step, args.total_steps)
    except Exception as exc:  # noqa: BLE001 — any problem => caller falls back to the
        # original conf, which is the pre-existing behaviour: no worse, never crashes the
        # ladder over a resume it could not write.
        sys.stderr.write("[nadoc-resume] cannot build a resume conf: %s\n" % exc)
        return 1

    with open("%s.resume.conf" % args.seg, "w") as fh:
        fh.write(text)
    sys.stderr.write("[nadoc-resume] %s resumes at step %d\n" % (args.seg, step))
    print(step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
