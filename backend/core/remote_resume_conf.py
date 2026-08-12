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
_RESUME_DROP = frozenset(
    [
        "binCoordinates",
        "binVelocities",
        "extendedSystem",
        "temperature",
        "reinitvels",
        "firsttimestep",
        "dcdFile",
        "xstFile",
        "run",
    ]
)

# ...and these, which the resume must re-emit. Their original cadence is retained when
# it is already denser than the minimum needed by a short continuation.
_RESUME_RECOMPUTE = frozenset(["outputEnergies", "dcdFreq", "xstFreq", "restartfreq"])

# Tier-A/B early-stop refuses to judge a plateau on fewer than CutoffParams.min_frames
# (20) ENERGY frames. Same target as md_protocols._ENERGY_FRAMES_PER_CHUNK.
_FRAMES_PER_CHUNK = 30
_STEPS_PER_CYCLE = 20


def _output_freq(steps):
    """Print interval giving ~30 frames for a chunk of ``steps`` — RECOMPUTED on resume.

    A resume runs ``total - restart_step``, not ``total``. Inheriting the original conf's
    step-denominated cadence therefore yields FEWER frames the later the restart happens:

        shrink at step   4,000 -> 116,000 left / 4,000 = 29 frames   (fine)
        shrink at step  44,000 ->  76,000 left / 4,000 = 19 frames   (UNDER min_frames!)

    ...and below 20 the evaluator reports "insufficient data", which fails SAFE to HOLD —
    so the chunk silently loses its ability to bridge and the stage runs in full. Exactly
    the same silent 4x-cost failure as the original hardcoded-9600 bug, just triggered by
    a cell shrink instead of by `fast`. Recompute from what is actually left to run.
    """
    f = max(_STEPS_PER_CYCLE, steps // _FRAMES_PER_CHUNK)
    return max(_STEPS_PER_CYCLE, f - (f % _STEPS_PER_CYCLE))


def _original_frequency(conf_text, directive):
    """Return a positive integer cadence from the original conf, if present."""
    for line in reversed(conf_text.splitlines()):
        fields = line.split()
        if fields and fields[0] == directive and len(fields) >= 2:
            try:
                value = int(fields[1])
            except ValueError:
                return None
            return value if value > 0 else None
    return None


def _resume_frequency(conf_text, directive, remaining):
    """Never make output sparser on resume; tighten it for very short tails."""
    target = _output_freq(remaining)
    original = _original_frequency(conf_text, directive)
    return min(original, target) if original is not None else target


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
            "resume step %d is at/past the segment total %d"
            % (restart_step, total_steps)
        )
    adaptive_min = "# NADOC_ADAPTIVE_MIN_BEGIN" in conf_text
    drop = _RESUME_DROP | _RESUME_RECOMPUTE
    kept = [
        line
        for line in conf_text.splitlines()
        if (line.split()[0] if line.split() else "") not in drop
    ]
    frequencies = {
        key: _resume_frequency(conf_text, key, remaining)
        for key in _RESUME_RECOMPUTE
    }
    tail = [
        "binCoordinates     output/%s.restart.coor" % segment_name,
        # THE fix: the shrunken cell. Supersedes any cellBasisVector still in the conf.
        "extendedSystem     output/%s.restart.xsc" % segment_name,
        "dcdFile            output/%s.dcd" % segment_name,
        "xstFile            output/%s.xst" % segment_name,
        # Preserve the original (possibly much denser) cadence, while tightening it for
        # a short tail when needed. Increasing these intervals on a long production
        # resume starves live health and leaves large amounts of work uncheckpointed.
        "outputEnergies     %d" % frequencies["outputEnergies"],
        "dcdFreq            %d" % frequencies["dcdFreq"],
        "xstFreq            %d" % frequencies["xstFreq"],
        "restartfreq        %d" % frequencies["restartfreq"],
        "firsttimestep      %d" % int(restart_step),
    ]
    if adaptive_min:
        # Continue minimising from the checkpoint. The controller's counters are local
        # to this invocation, so reduce both its hard ceiling and its not-before gate by
        # the already-paid work. Missing energy callbacks still fail safe to the reduced
        # ceiling exactly as in the original config.
        rewritten = []
        for line in kept:
            if line.startswith("set nadoc_min_max "):
                line = "set nadoc_min_max %d" % remaining
            elif line.startswith("set nadoc_min_min "):
                original_min = int(line.split()[-1])
                line = "set nadoc_min_min %d" % max(0, original_min - int(restart_step))
            rewritten.append(line)
        kept = rewritten
        # NAMD insists on an initialization source even though minimisation does not
        # integrate velocities. The original min config uses temperature 0; preserve
        # that semantic instead of loading the meaningless minimizer restart velocities.
        tail.insert(1, "temperature        0")
        # The adaptive block contains executable ``minimize`` commands. All startup
        # directives must precede it; appending them at EOF makes NAMD start before it
        # has coordinates/temperature and fail during config parsing.
        marker = kept.index("# NADOC_ADAPTIVE_MIN_BEGIN")
        kept[marker:marker] = tail
    else:
        tail.insert(1, "binVelocities      output/%s.restart.vel" % segment_name)
        # NAMD 3's Tcl `run` has no `upto`; firsttimestep already advanced the label, so
        # run only what is left. restart_step is a multiple of restartfreq (itself a
        # multiple of stepspercycle), so the remainder stays cycle-aligned.
        tail.append("run                %d" % remaining)
        kept += tail
    return "\n".join(kept) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="write <seg>.resume.conf from a checkpoint"
    )
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
