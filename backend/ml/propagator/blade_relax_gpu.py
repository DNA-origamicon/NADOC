"""BLADE implicit-solvent relax — THE GPU-ENV SCRIPT.

*** This module is NOT importable from the backend (uv) environment. ***
``openmm`` and ``parmed`` live only in the micromamba ``gpu`` environment, so this file is
executed as a SCRIPT by that environment's interpreter:

    /home/joshua/micromamba/envs/gpu/bin/python -m backend.ml.propagator.blade_relax_gpu <config.json>

(resolved via :func:`backend.core.engines.find_blade_python`).  ``backend/core/blade_worker.py``
is the uv-env half that spawns it and translates its stdout into job progress.  Keep this file
free of any backend import — it must stand alone under a foreign interpreter.

Method: CHARMM36 + OBC2 implicit solvent, NO periodic box, NO explicit water.  OpenMM
minimize + short LangevinMiddle settling.  A ``CutoffNonPeriodic`` nonbonded cutoff (default
18 Å) keeps GBSA ~O(N), so a 40k-atom origami relaxes in minutes on GPU instead of hitting the
O(N²) NoCutoff wall.  Promoted verbatim-in-physics from the seeding-benchmark driver that
produced the STABLE curved-6hb relax (72 s); the additions here are the JSON config interface,
the per-step progress stream, and the result JSON.

Protocol with the worker: every line on stdout is one JSON object with an ``event`` key.
  {"event":"platform", "using":"CUDA", "n":41234, "cutoff_A":18.0}
  {"event":"progress", "fraction":0.42, "phase":"langevin", "step":1200, "n_steps":3000}
  {"event":"result",   ...summary fields...}
  {"event":"error",    "message":"..."}
"""

import json
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import openmm as mm
import parmed as pmd
from openmm import app, unit
from parmed.charmm import CharmmParameterSet


def log(**kw):
    """Emit one JSON line.  ``flush`` matters — the worker reads this stream live."""
    print(json.dumps(kw), flush=True)


class _ProgressReporter:
    """OpenMM reporter that turns the Langevin leg into a progress fraction.

    The minimize leg occupies ``0 → _MIN_FRAC``; Langevin spans the rest.  Reporting is
    step-driven (OpenMM calls us every ``interval`` steps), and the worker throttles further,
    so a long run costs a few hundred tiny writes rather than one per step.
    """

    _MIN_FRAC = 0.25

    def __init__(self, interval, total_steps):
        self._interval = max(1, int(interval))
        self._total = max(1, int(total_steps))

    def describeNextReport(self, simulation):
        steps = self._interval - simulation.currentStep % self._interval
        # (steps, positions, velocities, forces, energies, wrapVelocities)
        return (steps, False, False, False, False, False)

    def report(self, simulation, state):
        step = simulation.currentStep
        frac = self._MIN_FRAC + (1.0 - self._MIN_FRAC) * min(1.0, step / self._total)
        log(
            event="progress",
            fraction=round(frac, 4),
            phase="langevin",
            step=int(step),
            n_steps=self._total,
        )


def rg(x):
    """Radius of gyration (Å) of a coordinate array."""
    c = x - x.mean(0)
    return float(np.sqrt((c**2).sum(-1).mean()))


def blade_relax(
    solute_pdb,
    psf_path,
    ff_dir,
    out_pdb,
    *,
    n_solute=None,
    minimize_iters=400,
    langevin_ps=3.0,
    dt_fs=1.0,
    gamma_ps=50.0,
    platform="CUDA",
    temp_K=300.0,
    traj_dcd=None,
    traj_frames=60,
    nb_cutoff_A=18.0,
):
    """Relax the first ``n_solute`` atoms of the PSF under CHARMM+OBC2 implicit solvent.

    Uses OpenMM's constrained LangevinMiddle integrator (HBonds + HMR) so dt = 1–2 fs is
    stable, unlike an unconstrained custom BAOAB.  Writes the relaxed coordinates to
    ``out_pdb`` in the SAME atom order as the input (this is what makes the result usable as
    a NAMD seed).  Returns the summary dict that becomes ``result.json``.
    """
    psf = pmd.charmm.CharmmPsfFile(psf_path)
    psf.load_parameters(
        CharmmParameterSet(
            f"{ff_dir}/top_all36_na.rtf",
            f"{ff_dir}/par_all36_na.prm",
            f"{ff_dir}/toppar_water_ions_cufix.str",
            f"{ff_dir}/par_stub_ions_nbfix.str",
        )
    )
    sub = psf if n_solute is None else psf[f"@1-{n_solute}"]

    sysm = sub.createSystem(
        nonbondedMethod=app.CutoffNonPeriodic,
        nonbondedCutoff=nb_cutoff_A * unit.angstrom,
        implicitSolvent=app.OBC2,
        implicitSolventSaltConc=0.15 * unit.moles / unit.liter,
        constraints=app.HBonds,
        hydrogenMass=1.5 * unit.amu,
    )
    integ = mm.LangevinMiddleIntegrator(
        temp_K * unit.kelvin, gamma_ps / unit.picosecond, dt_fs * unit.femtoseconds
    )

    used = platform
    try:
        sim = app.Simulation(
            sub.topology, sysm, integ, mm.Platform.getPlatformByName(platform)
        )
    except Exception as e:
        # A CUDA-less box (or a card already saturated by a production job) must not hard-fail
        # the run — fall back and RECORD it, so the panel can show "ran on CPU".
        log(event="platform_fallback", requested=platform, error=str(e)[:300])
        used = "CPU"
        sim = app.Simulation(
            sub.topology, sysm, integ, mm.Platform.getPlatformByName("CPU")
        )
    log(event="platform", using=used, n=len(sub.atoms), cutoff_A=nb_cutoff_A)

    pdb = app.PDBFile(solute_pdb)
    pos0 = np.array(pdb.getPositions().value_in_unit(unit.angstrom))
    sim.context.setPositions(pdb.positions)

    steps = int(langevin_ps * 1000 / dt_fs)
    every = max(1, steps // max(1, traj_frames))

    # Escalating minimization retry.  A dense bundle's idealized B-DNA build has severe
    # inter-helix crossover clashes; too few minimization iterations leave a contact that
    # explodes into a NaN on the first Langevin step (observed on a 102k-atom 18hb at 300–400
    # iters).  So: minimize + settle at the requested budget, and if that yields a non-finite
    # coordinate, RESET to the ideal coords and retry with far more minimization — finally
    # running to convergence (maxIterations=0).  Each retry only repeats minimize+settle; the
    # (slow) system build is not redone.  ``used_minimize_iters`` records what actually worked.
    def _finite(arr):
        return bool(np.isfinite(arr).all())

    schedule = []
    for mi in (int(minimize_iters), max(int(minimize_iters) * 8, 4000), 0):
        if mi not in schedule:  # 0 = minimize to convergence (OpenMM: no iteration cap)
            schedule.append(mi)

    t = time.time()
    x = None
    used_mi = None
    attempts = 0
    last_err = None
    for attempt, mi in enumerate(schedule):
        attempts = attempt + 1
        sim.reporters.clear()  # drop a failed attempt's reporters
        sim.context.setPositions(pdb.positions)  # always restart from the ideal coords
        if attempt:
            log(
                event="minimize_retry",
                attempt=attempt,
                minimize_iters=mi,
                reason=last_err,
            )
        n_disp = mi if mi else steps  # a "converge" run has no fixed iter count
        log(
            event="progress",
            fraction=0.02,
            phase="minimize",
            step=0,
            n_steps=int(n_disp),
        )
        sim.minimizeEnergy(maxIterations=mi)
        xmin = (
            sim.context.getState(getPositions=True)
            .getPositions(asNumpy=True)
            .value_in_unit(unit.angstrom)
        )
        if not _finite(np.asarray(xmin)):
            last_err = "non-finite coordinates after minimization"
            continue
        log(
            event="progress",
            fraction=_ProgressReporter._MIN_FRAC,
            phase="minimize",
            step=int(n_disp),
            n_steps=int(n_disp),
        )
        sim.context.setVelocitiesToTemperature(temp_K * unit.kelvin)
        # DCD is (re)opened fresh per attempt (truncating), so only the surviving run's frames
        # remain; attach it only now, after minimization produced a finite structure.
        if traj_dcd:
            sim.reporters.append(app.DCDReporter(traj_dcd, every))
        sim.reporters.append(_ProgressReporter(every, steps))
        try:
            sim.step(steps)
            cand = np.array(
                sim.context.getState(getPositions=True)
                .getPositions(asNumpy=True)
                .value_in_unit(unit.angstrom)
            )
        except Exception as exc:  # OpenMM raises "Particle coordinate is NaN"
            last_err = f"{type(exc).__name__}: {str(exc)[:200]}"
            continue
        if _finite(cand):
            x = cand
            used_mi = mi
            break
        last_err = "non-finite coordinates after Langevin settling"

    if x is None:
        raise RuntimeError(
            f"relax blew up after {attempts} minimization attempt(s) "
            f"(last: {last_err}) — the structure may be too clashed to relax"
        )
    finite = True
    with open(out_pdb, "w") as fh:
        app.PDBFile.writeFile(sub.topology, x * unit.angstrom, fh)

    # Kabsch-aligned RMSD: how far the structure actually travelled, rigid motion removed.
    ac = pos0 - pos0.mean(0)
    bc = x - x.mean(0)
    U, S, Vt = np.linalg.svd(ac.T @ bc)
    D = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, D]) @ U.T
    rmsd = float(np.sqrt(((ac @ R.T - bc) ** 2).sum(-1).mean()))

    # bbox diagonal before/after — the straighten/collapse tell.
    span0 = float(np.linalg.norm(pos0.max(0) - pos0.min(0)))
    span1 = float(np.linalg.norm(x.max(0) - x.min(0)))

    return {
        "out": out_pdb,
        "traj": traj_dcd,
        "n_atoms": len(x),
        "finite": finite,
        "platform_used": used,
        # What minimization budget actually produced a stable relax (0 = ran to convergence),
        # and how many attempts it took — so a big design that needed escalation is visible.
        "used_minimize_iters": used_mi,
        "relax_attempts": attempts,
        "rmsd_moved_A": round(rmsd, 3),
        "rg_before_A": round(rg(pos0), 3),
        "rg_after_A": round(rg(x), 3),
        "bbox_diag_before_A": round(span0, 2),
        "bbox_diag_after_A": round(span1, 2),
        "n_frames": steps // every,
        "wall_s": round(time.time() - t, 1),
    }


def main(argv):
    if len(argv) < 2:
        log(event="error", message="usage: blade_relax_gpu.py <config.json>")
        return 2
    cfg = json.loads(open(argv[1]).read())
    try:
        summary = blade_relax(
            cfg["solute_pdb"],
            cfg["psf_path"],
            cfg["ff_dir"],
            cfg["out_pdb"],
            n_solute=cfg.get("n_solute"),
            minimize_iters=cfg.get("minimize_iters", 400),
            langevin_ps=cfg.get("langevin_ps", 3.0),
            dt_fs=cfg.get("dt_fs", 1.0),
            gamma_ps=cfg.get("gamma_ps", 50.0),
            platform=cfg.get("platform", "CUDA"),
            temp_K=cfg.get("temp_K", 300.0),
            traj_dcd=cfg.get("traj_dcd"),
            traj_frames=cfg.get("traj_frames", 60),
            nb_cutoff_A=cfg.get("nb_cutoff_A", 18.0),
        )
    except Exception as exc:
        log(event="error", message=f"{type(exc).__name__}: {exc}")
        return 1
    log(event="progress", fraction=1.0, phase="done")
    log(event="result", **summary)
    if cfg.get("result_json"):
        with open(cfg["result_json"], "w") as fh:
            json.dump(summary, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
