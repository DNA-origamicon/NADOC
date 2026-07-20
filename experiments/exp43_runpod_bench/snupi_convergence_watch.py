#!/usr/bin/env python3
"""Periodic SNUPI-convergence checker + auto-terminator for a running NAMD production.

WHAT IT ANSWERS  "Has the post-equilibration ensemble collected enough decorrelated frames
to re-estimate SNUPI's elastic parameters, and if so, stop paying for more?"  SNUPI's
per-motif stiffness is k ∝ 1/Var(bp-step params); the two dominant, most robust DOF are
helical **twist** (torsional rigidity GJ) and **rise** (stretch EA).  We track the pooled
per-frame twist & rise and watch the *ensemble variance* stabilise.

HOW  Each poll runs ``snupi_worker.py`` — self-contained numpy — over the STILL-GROWING DCD:
  * pod run  : SSH to the existing pod, worker reads the pod-local DCD (no 100 GB fetch),
               state file persists ON the pod so each poll only reads the new frames.
  * local run: worker runs as a subprocess over the local DCD.
The returned per-frame series is fed to ``detect_equilibration`` (burn-in t0) then a two-half
stability test on the ensemble variance (and residual mean drift).  Converged = variance
drift < tol AND mean drift < a fraction of the fluctuation, for BOTH twist and rise, over
``--stable-passes`` consecutive polls.

ON CONVERGENCE  pod: terminate_pod + close the spend ledger (stops billing) and drop a
sentinel; local: alert (free compute) unless ``--kill-local``.
ON PERSISTENT FAILURE  loud alert + sentinel; does NOT auto-destroy a maybe-healthy pod on
ssh flakiness alone (crash-reaping is the pod watchdog's job) — but surfaces it so a human acts.

    python snupi_convergence_watch.py --pod-id <POD> --job-id <JOB> \
        --recipe 2xT_recipe.npy --interval-sec 1800 --terminate
    python snupi_convergence_watch.py --local --job-id <JOB> \
        --dcd /path/prod.dcd --recipe 1xT_recipe.npy --interval-sec 1800
"""
from __future__ import annotations
import argparse, asyncio, json, subprocess, sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

from backend.core.oxdna_health import detect_equilibration  # noqa: E402

KEY_FILE = Path.home() / ".runpod_key"
LEDGER_ROOT = Path("/media/jojo/Archive/nadoc_jobs")
REMOTE_DIR = "/workspace/snupi_check"


# ── convergence assessment (pure, local) ──────────────────────────────────────
def _ensemble_var(mean_s, var_s):
    """Law of total variance: E_f[Var_step] (spatial, fast) + Var_f[mean_step] (temporal, slow)."""
    return float(np.mean(var_s) + np.var(mean_s))


def _blockstats(mean_s, var_s, nb):
    """Block the post-eq window into nb contiguous blocks; per-block ensemble variance V_b.
    Returns (V, rel_sem, drift): V=mean(V_b); rel_sem=SEM(V_b)/V (residual stiffness precision,
    valid only when stationary); drift=|linear slope|*span/V (ongoing-equilibration trend)."""
    idx = np.array_split(np.arange(len(mean_s)), nb)
    Vb = np.array([_ensemble_var(mean_s[ix], var_s[ix]) for ix in idx])
    V = float(Vb.mean())
    if V <= 0:
        return V, 1.0, 1.0
    rel_sem = float(Vb.std(ddof=1) / np.sqrt(nb) / V)
    slope = float(np.polyfit(np.arange(nb), Vb, 1)[0])
    drift = abs(slope * (nb - 1)) / V
    return V, rel_sem, drift


def assess(series, dt_ps, sem_tol=0.05, drift_tol=0.05, min_post=200):
    """series row = [frame, tw_mean, tw_var, ri_mean, ri_var, n_steps]. Returns a report dict.

    SNUPI stiffness k ∝ 1/Var(step param). For each DOF we take the post-burn-in ensemble
    variance and, over contiguous blocks, require BOTH:
      * drift < drift_tol  — no residual trend (the fluctuation amplitude has stopped settling), AND
      * rel_sem < sem_tol  — the achieved statistical precision on the stiffness is tight enough.
    rel_sem alone is deceptive while a trend remains (blocks look precise but are marching), so
    the drift gate is the primary equilibration signal; rel_sem is the sufficiency (frame-count) gate.
    """
    a = np.array(series, dtype=float)
    out = {"n_frames": len(a), "ns": round(len(a) * dt_ps / 1000.0, 2),
           "converged": False, "dofs": {}}
    if len(a) < max(120, min_post):
        out["reason"] = f"only {len(a)} frames (< {min_post})"
        return out
    # ONE shared burn-in from the dominant twist DOF (the slow global mode). We take the LATER
    # of the twist MEAN and twist VARIANCE burn-ins: the mean equilibrates first (~0.3 ns) but
    # SNUPI's quantity is the VARIANCE, which plateaus later — including its decay transient
    # keeps `drift` spuriously high. (detect_equilibration on the near-flat rise is unreliable;
    # twist bounds both DOF.)
    t0 = max(int(detect_equilibration(a[:, 1].tolist())["t0"]),
             int(detect_equilibration(a[:, 2].tolist())["t0"]))
    t0 = min(t0, len(a) - min_post) if len(a) - min_post > 0 else 0
    out["t0_ns"] = round(t0 * dt_ps / 1000, 2)
    ok_all = True
    for key, mi, vi in [("twist", 1, 2), ("rise", 3, 4)]:
        mean_s, var_s = a[:, mi], a[:, vi]
        mp, vp = mean_s[t0:], var_s[t0:]
        n = len(mp)
        if n < min_post:
            ok_all = False
            out["dofs"][key] = {"t0_ns": round(t0 * dt_ps / 1000, 2), "post": n,
                                "converged": False, "reason": "post<min"}
            continue
        nb = int(np.clip(n // 40, 6, 12))
        V, rel_sem, drift = _blockstats(mp, vp, nb)
        conv = (drift < drift_tol) and (rel_sem < sem_tol)
        ok_all = ok_all and conv
        out["dofs"][key] = {"t0_ns": round(t0 * dt_ps / 1000, 2), "post": n, "nb": nb,
                            "V": round(V, 4), "stiff_prec_pct": round(rel_sem * 100, 1),
                            "drift_pct": round(drift * 100, 1), "converged": conv}
    out["converged"] = ok_all
    return out


# ── worker invocation (local subprocess / pod ssh) ────────────────────────────
def run_worker_local(dcd: str, recipe: str, state: str) -> dict:
    p = subprocess.run(
        [sys.executable, str(HERE / "snupi_worker.py"),
         "--dcd", dcd, "--recipe", recipe, "--state", state],
        capture_output=True, text=True, timeout=1200)
    if p.returncode != 0:
        return {"error": f"worker rc={p.returncode}: {p.stderr.strip()[-300:]}"}
    return json.loads(p.stdout)


async def run_worker_pod(conn, dcd: str, recipe_remote: str, state_remote: str) -> dict:
    r = await conn.run(
        f"cd {REMOTE_DIR} && python3 snupi_worker.py --dcd {dcd!r} "
        f"--recipe {recipe_remote!r} --state {state_remote!r}", timeout=1200)
    if r.rc != 0:
        return {"error": f"pod worker rc={r.rc}: {(r.stderr or '').strip()[-300:]}"}
    try:
        return json.loads(r.stdout)
    except Exception as e:
        return {"error": f"pod worker bad json: {e}: {r.stdout[:200]}"}


# ── termination ───────────────────────────────────────────────────────────────
async def reap_pod(pod_id: str, reason: str) -> str:
    from backend.core.runpod_api import RunpodClient
    from experiments.exp43_runpod_bench.spend_ledger import SpendLedger
    client = RunpodClient(KEY_FILE.read_text().strip())
    try:
        await client.terminate_pod(pod_id)
        for f in sorted(LEDGER_ROOT.glob("*/spend.json")):
            try: SpendLedger(f).close_pod(pod_id)
            except Exception: pass
        left = [p.id for p in await client.list_pods() if not p.is_destroyed]
        return f"reaped {pod_id} ({reason}); still on account: {left or 'none'}"
    finally:
        await client.aclose()


def _sentinel(job_id: str, payload: dict):
    out = LEDGER_ROOT / job_id / "snupi_convergence.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2))
    except Exception as e:
        print(f"[warn] could not write sentinel: {e}", flush=True)


def _log(msg: str):
    print(f"[snupi-watch {time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def _connect_pod(pod_id: str):
    """Fresh SSH connection to an existing pod (raises if the pod is gone/destroyed).
    Reconnecting per-poll — not holding one link for ~29 h — is what survives SSH drops."""
    from backend.core.runpod_api import RunpodClient, ssh_endpoint
    from backend.core.runpod_conn import RunpodConnection
    client = RunpodClient(KEY_FILE.read_text().strip())
    try:
        pod = {p.id: p for p in await client.list_pods()}.get(pod_id)
    finally:
        await client.aclose()
    if pod is None or pod.is_destroyed:
        raise RuntimeError(f"pod {pod_id} not on account / destroyed")
    host, port = ssh_endpoint(pod)
    conn = RunpodConnection(host=host, port=port, pod_id=pod.id,
                            client_keys=[str(Path.home() / ".ssh" / "id_ed25519")])
    await conn.connect()
    return conn


# ── main loop ─────────────────────────────────────────────────────────────────
async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--interval-sec", type=int, default=1800)
    ap.add_argument("--stable-passes", type=int, default=2)
    ap.add_argument("--sem-tol", type=float, default=0.05, help="max block rel-SEM of V (stiffness precision)")
    ap.add_argument("--drift-tol", type=float, default=0.05, help="max residual trend in V across blocks")
    ap.add_argument("--min-post", type=int, default=200)
    ap.add_argument("--max-fails", type=int, default=6)
    ap.add_argument("--max-polls", type=int, default=200)
    ap.add_argument("--once", action="store_true", help="single assessment, no loop/terminate")
    # local mode
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--dcd", help="local DCD path (local mode)")
    ap.add_argument("--kill-local", action="store_true", help="SIGTERM the local NAMD on convergence")
    # pod mode
    ap.add_argument("--pod-id")
    ap.add_argument("--pod-dcd-glob", default=f"/workspace/nadoc_jobs/JOBID/output/*production*.dcd")
    ap.add_argument("--terminate", action="store_true", help="reap the pod on convergence")
    a = ap.parse_args()

    recipe = str(Path(a.recipe).resolve())
    state_local = str(HERE / f".snupi_state_{a.job_id}.json")
    n_steps = int(np.load(recipe).shape[0])
    _log(f"job {a.job_id}  recipe {n_steps} steps  interval {a.interval_sec}s  "
         f"stable-passes {a.stable_passes}  {'LOCAL' if a.local else 'POD ' + str(a.pod_id)}")

    pod_dcd = None
    if not a.local:
        # one-time staging on the network volume (persists across reconnects)
        try:
            conn = await _connect_pod(a.pod_id)
        except Exception as e:
            _log(f"FATAL: {e}"); return 2
        try:
            await conn.mkdir_p(REMOTE_DIR)
            for f in ("snupi_worker.py", "dcd_fast.py"):
                await conn.sftp_put(str(HERE / f), f"{REMOTE_DIR}/{f}")
            await conn.sftp_put(recipe, f"{REMOTE_DIR}/recipe.npy")
            glob = a.pod_dcd_glob.replace("JOBID", a.job_id)
            pod_dcd = (await conn.run(f"ls -1t {glob} 2>/dev/null | head -1")).stdout.strip()
        finally:
            await conn.close()
        if not pod_dcd:
            _log(f"FATAL: no DCD matching {glob} on pod"); return 2
        _log(f"pod DCD: {pod_dcd}")

    fails = 0; good = 0
    for poll in range(a.max_polls):
        try:
            if a.local:
                rep = run_worker_local(a.dcd, recipe, state_local)
            else:
                conn = await _connect_pod(a.pod_id)   # fresh link each poll
                try:
                    rep = await run_worker_pod(conn, pod_dcd, f"{REMOTE_DIR}/recipe.npy",
                                               f"{REMOTE_DIR}/state.json")
                finally:
                    await conn.close()
        except Exception as e:
            rep = {"error": f"{type(e).__name__}: {e}"}

        if "error" in rep:
            fails += 1
            _log(f"poll {poll}: WORKER FAIL ({fails}/{a.max_fails}) {rep['error']}")
            if fails >= a.max_fails:
                _sentinel(a.job_id, {"status": "failed", "error": rep["error"],
                                     "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
                _log("ALERT: persistent worker failures — human should check the run/pod")
                return 3
            if a.once: return 3
            await asyncio.sleep(min(a.interval_sec, 300)); continue
        fails = 0

        rp = assess(rep.get("series", []), rep.get("dt_ps", 4.0),
                    sem_tol=a.sem_tol, drift_tol=a.drift_tol, min_post=a.min_post)
        dof = rp.get("dofs", {})
        tw = dof.get("twist", {}); ri = dof.get("rise", {})
        _log(f"poll {poll}: {rp['ns']}ns ({rp['n_frames']}fr)  "
             f"twist[t0={tw.get('t0_ns','?')}ns post={tw.get('post','?')} "
             f"drift={tw.get('drift_pct','?')}% prec={tw.get('stiff_prec_pct','?')}% "
             f"{'OK' if tw.get('converged') else '..'}]  "
             f"rise[drift={ri.get('drift_pct','?')}% prec={ri.get('stiff_prec_pct','?')}% "
             f"{'OK' if ri.get('converged') else '..'}]  "
             f"=> {'CONVERGED' if rp['converged'] else rp.get('reason','not yet')}")
        _sentinel(a.job_id, {"status": "converged" if rp["converged"] else "running",
                             "assessment": rp, "consecutive_good": good,
                             "ts": time.strftime("%Y-%m-%d %H:%M:%S")})

        if a.once:
            return 0

        good = good + 1 if rp["converged"] else 0
        if good >= a.stable_passes:
            _log(f"CONVERGED for {good} consecutive polls at {rp['ns']}ns.")
            msg = {"status": "converged_final", "assessment": rp,
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            if a.local:
                if a.kill_local:
                    subprocess.run(["pkill", "-TERM", "-f",
                                    f"namd.*{a.job_id}"], check=False)
                    msg["action"] = "SIGTERM local NAMD"
                else:
                    msg["action"] = "alert only (local, free compute — left running)"
                _log(msg["action"])
            elif a.terminate:
                msg["action"] = await reap_pod(a.pod_id, f"SNUPI converged @ {rp['ns']}ns")
                _log(msg["action"])
            else:
                msg["action"] = "alert only (--terminate not set)"
                _log(msg["action"])
            _sentinel(a.job_id, msg)
            return 0

        await asyncio.sleep(a.interval_sec)

    _log("max polls reached without convergence")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
