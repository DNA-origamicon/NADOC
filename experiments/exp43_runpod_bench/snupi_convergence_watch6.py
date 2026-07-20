#!/usr/bin/env python3
"""Per-motif 6x6-covariance SNUPI convergence checker + auto-terminator (full-DOF successor).

Gates on the convergence of each motif's ENSEMBLE covariance eigenvalues — SNUPI stiffness is
k = kB*T*Cov^-1, so the eigenvalues (which fold in the off-diagonal couplings) are the right target.
Two motifs: duplex (regular_bp; fast) and the extra-base CROSSOVER (the deliverable; slow — its
rotational DOF are intrinsically noisy at junctions, so the DRIFT gate leads and rel-SEM is looser).

Runs snupi_worker6.py over the growing DCD (pod via ssh / local subprocess), same daemon skeleton as
snupi_convergence_watch.py (reconnect-per-poll, sentinel, reap-on-converge). Terminate fires only when
the CROSSOVER motif converges (the paid-MD deliverable); duplex is reported as a sanity check.
"""
from __future__ import annotations
import argparse, asyncio, json, subprocess, sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent
from backend.core.oxdna_health import detect_equilibration           # noqa: E402
from snupi_convergence_watch import (_connect_pod, reap_pod, _sentinel,  # noqa: E402
                                     _log, REMOTE_DIR, KEY_FILE)

_UT = np.triu_indices(6)
_DIAG = (_UT[0] == _UT[1])              # which of the 21 upper-tri entries are the diagonal


def _sym6(ut):
    C = np.zeros((6, 6)); C[_UT] = ut
    return C + C.T - np.diag(np.diag(C))


def _ensemble_cov(means, covs_ut):
    """means (F,6), covs_ut (F,21) -> ensemble covariance (6,6): mean spatial + cov of per-frame means."""
    C = _sym6(covs_ut.mean(axis=0))
    return C + np.cov(means.T)


def assess6(series, dt_ps, mkey, ckey, sem_tol, drift_tol, min_post, eig_floor=1e-6):
    """Convergence of one motif's ensemble-covariance eigenvalues over post-burn-in blocks."""
    rows = [r for r in series if mkey in r and ckey in r]
    out = {"n": len(rows), "converged": False}
    if len(rows) < max(120, min_post):
        out["reason"] = f"{len(rows)} frames (<{min_post})"; return out
    means = np.array([r[mkey] for r in rows], float)      # (F,6)
    covs = np.array([r[ckey] for r in rows], float)        # (F,21)
    trace = covs[:, _DIAG].sum(axis=1)                     # total spatial variance (fluctuation size)
    t0 = int(detect_equilibration(trace.tolist())["t0"])
    t0 = min(t0, len(rows) - min_post) if len(rows) - min_post > 0 else 0
    m_p, c_p = means[t0:], covs[t0:]; n = len(m_p)
    out["t0_ns"] = round(t0 * dt_ps / 1000, 2); out["post"] = n
    if n < min_post:
        out["reason"] = "post<min"; return out
    nb = int(np.clip(n // 40, 6, 12)); out["nb"] = nb
    eb = []
    for ix in np.array_split(np.arange(n), nb):
        V = _ensemble_cov(m_p[ix], c_p[ix])
        eb.append(np.sort(np.linalg.eigvalsh(V))[::-1])
    eb = np.array(eb)                                       # (nb,6) eigenvalues, desc
    conv = True; eigs = []
    for e in range(6):
        vb = eb[:, e]; V = float(vb.mean())
        if V <= eig_floor:
            eigs.append({"eig": round(V, 4), "ok": False, "why": "degenerate"}); conv = False; continue
        rsem = float(vb.std(ddof=1) / np.sqrt(nb) / V)
        drift = abs(float(np.polyfit(np.arange(nb), vb, 1)[0]) * (nb - 1)) / V
        ok = (drift < drift_tol) and (rsem < sem_tol)
        conv = conv and ok
        eigs.append({"eig": round(V, 3), "drift_pct": round(drift * 100, 1),
                     "prec_pct": round(rsem * 100, 1), "ok": ok})
    out["converged"] = conv; out["eigs"] = eigs
    return out


def run_worker_local(dcd, recipe, state):
    p = subprocess.run([sys.executable, str(HERE / "snupi_worker6.py"),
                        "--dcd", dcd, "--recipe", recipe, "--state", state],
                       capture_output=True, text=True, timeout=3600)
    if p.returncode != 0:
        return {"error": f"worker rc={p.returncode}: {p.stderr.strip()[-300:]}"}
    return json.loads(p.stdout)


async def run_worker_pod(conn, dcd, recipe_remote, state_remote):
    r = await conn.run(f"cd {REMOTE_DIR} && python3 snupi_worker6.py --dcd {dcd!r} "
                       f"--recipe {recipe_remote!r} --state {state_remote!r}", timeout=3600)
    if r.rc != 0:
        return {"error": f"pod worker rc={r.rc}: {(r.stderr or '').strip()[-300:]}"}
    try:
        return json.loads(r.stdout)
    except Exception as e:
        return {"error": f"pod worker bad json: {e}: {r.stdout[:200]}"}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--recipe", required=True)          # .npz (dup_* + xo_*)
    ap.add_argument("--interval-sec", type=int, default=1800)
    ap.add_argument("--stable-passes", type=int, default=2)
    ap.add_argument("--sem-tol", type=float, default=0.10, help="max block rel-SEM of an eigenvalue")
    ap.add_argument("--drift-tol", type=float, default=0.05, help="max residual trend of an eigenvalue")
    ap.add_argument("--min-post", type=int, default=200)
    ap.add_argument("--max-fails", type=int, default=6)
    ap.add_argument("--max-polls", type=int, default=400)
    ap.add_argument("--stall-reap-polls", type=int, default=3,
                    help="reap the pod if the DCD frame count is unchanged this many consecutive polls "
                         "(run finished at 30 ns / died) — guarantees termination, no idle billing")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--dcd")
    ap.add_argument("--pod-id")
    ap.add_argument("--pod-dcd-glob", default="/workspace/nadoc_jobs/JOBID/output/*production*.dcd")
    ap.add_argument("--terminate", action="store_true")
    a = ap.parse_args()

    recipe = str(Path(a.recipe).resolve())
    state_local = str(HERE / f".snupi6_state_{a.job_id}.json")
    _log(f"[6dof] job {a.job_id}  interval {a.interval_sec}s  {'LOCAL' if a.local else 'POD '+str(a.pod_id)}")

    pod_dcd = None
    if not a.local:
        try:
            conn = await _connect_pod(a.pod_id)
        except Exception as e:
            _log(f"FATAL: {e}"); return 2
        try:
            await conn.mkdir_p(REMOTE_DIR)
            for f in ("snupi_worker6.py", "dcd_fast.py", "snupi_step_params.py"):
                await conn.sftp_put(str(HERE / f), f"{REMOTE_DIR}/{f}")
            await conn.sftp_put(recipe, f"{REMOTE_DIR}/recipe6.npz")
            glob = a.pod_dcd_glob.replace("JOBID", a.job_id)
            pod_dcd = (await conn.run(f"ls -1t {glob} 2>/dev/null | head -1")).stdout.strip()
        finally:
            await conn.close()
        if not pod_dcd:
            _log("FATAL: no pod DCD"); return 2
        _log(f"pod DCD: {pod_dcd}")

    fails = 0; good = 0; prev_nframes = -1; stall = 0
    for poll in range(a.max_polls):
        try:
            if a.local:
                rep = run_worker_local(a.dcd, recipe, state_local)
            else:
                conn = await _connect_pod(a.pod_id)
                try:
                    rep = await run_worker_pod(conn, pod_dcd, f"{REMOTE_DIR}/recipe6.npz",
                                               f"{REMOTE_DIR}/state6.json")
                finally:
                    await conn.close()
        except Exception as e:
            rep = {"error": f"{type(e).__name__}: {e}"}
        if "error" in rep:
            fails += 1
            _log(f"poll {poll}: FAIL ({fails}/{a.max_fails}) {rep['error']}")
            if fails >= a.max_fails:
                _sentinel(a.job_id, {"status": "failed", "error": rep["error"],
                                     "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
                return 3
            if a.once: return 3
            await asyncio.sleep(min(a.interval_sec, 300)); continue
        fails = 0
        series = rep.get("series", []); dt = rep.get("dt_ps", 4.0)
        dup = assess6(series, dt, "dm", "dc", a.sem_tol, a.drift_tol, a.min_post)
        xo = assess6(series, dt, "xm", "xc", a.sem_tol, a.drift_tol, a.min_post)
        ns = round(len(series) * dt / 1000, 2)
        def _mx(r, k): return max((e.get(k, 0) for e in r.get("eigs", [{}])), default=0)
        _log(f"poll {poll}: {ns}ns ({len(series)}fr)  "
             f"duplex[post={dup.get('post','?')} maxdrift={_mx(dup,'drift_pct'):.1f}% "
             f"{'OK' if dup.get('converged') else '..'}]  "
             f"XOVER[post={xo.get('post','?')} maxdrift={_mx(xo,'drift_pct'):.1f}% "
             f"maxprec={_mx(xo,'prec_pct'):.1f}% {'OK' if xo.get('converged') else '..'}]  "
             f"=> {'CONVERGED' if xo.get('converged') else xo.get('reason','xover not yet')}")
        _sentinel(a.job_id, {"status": "converged" if xo.get("converged") else "running",
                             "duplex": dup, "crossover": xo, "ns": ns, "consecutive_good": good,
                             "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
        if a.once:
            return 0
        # run-finished backstop: DCD stopped growing -> production done (30 ns) or died -> reap now.
        nf = rep.get("n_frames", -1)
        stall = stall + 1 if nf == prev_nframes else 0
        prev_nframes = nf
        if stall >= a.stall_reap_polls and not a.local:
            _log(f"DCD stalled at {nf} frames for {stall} polls -> run finished; reaping.")
            msg = {"status": "reaped_run_finished", "crossover": xo, "duplex": dup, "ns": ns,
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            msg["action"] = (await reap_pod(a.pod_id, f"run finished @ {ns}ns (not converged)")
                             if a.terminate else "alert only (--terminate off)")
            _log(msg["action"]); _sentinel(a.job_id, msg)
            return 0
        good = good + 1 if xo.get("converged") else 0
        if good >= a.stable_passes:
            _log(f"CROSSOVER CONVERGED for {good} polls at {ns}ns.")
            msg = {"status": "converged_final", "crossover": xo, "duplex": dup, "ns": ns,
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            if a.local:
                msg["action"] = "alert only (local, free)"
            elif a.terminate:
                msg["action"] = await reap_pod(a.pod_id, f"SNUPI xover 6x6 converged @ {ns}ns")
            else:
                msg["action"] = "alert only (--terminate off)"
            _log(msg["action"]); _sentinel(a.job_id, msg)
            return 0
        await asyncio.sleep(a.interval_sec)
    _log("max polls reached"); return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
