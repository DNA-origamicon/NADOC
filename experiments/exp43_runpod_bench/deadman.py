#!/usr/bin/env python3
"""Pod-side deadman's switch — self-terminates the pod when the CONTROLLER goes dark.

The controller (blade_capture_driver) refreshes a heartbeat file on /workspace every
poll. If that file goes stale past DEADMAN_TOL_S (controller crashed / machine slept /
network dropped), this loop kills NAMD and TERMINATES THE POD ITSELF — the only thing
that stops billing when every controller-side backstop has died with the controller.

Terminate order (first that works wins), preferring zero-secret paths:
  1. runpodctl remove pod $RUNPOD_POD_ID   (pod-scoped, no secret leaves the machine)
  2. REST DELETE with RUNPOD_KILL_KEY (injected) or the pod-scoped RUNPOD_API_KEY
  3. curl fallback (dodges any urllib Cloudflare fingerprint block)

Env: RUNPOD_POD_ID (auto), CTRL_HEARTBEAT, DEADMAN_TOL_S, DEADMAN_POLL_S,
     RUNPOD_KILL_KEY (optional injected key), RUNPOD_API_KEY (auto pod-scoped).
"""
import os
import subprocess
import sys
import time
import urllib.request


def _pid1_env(name: str) -> str:
    """RunPod injects RUNPOD_POD_ID / RUNPOD_API_KEY into the container's PID-1 env,
    which an SSH-launched process does NOT inherit. Read them from /proc/1/environ."""
    try:
        with open("/proc/1/environ", "rb") as f:
            for kv in f.read().split(b"\0"):
                k, _, v = kv.partition(b"=")
                if k.decode(errors="ignore") == name:
                    return v.decode(errors="ignore")
    except Exception:
        pass
    return ""


# Prefer explicit (controller-passed) values; fall back to PID-1 env (RunPod's injection).
POD_ID = os.environ.get("RUNPOD_POD_ID", "") or _pid1_env("RUNPOD_POD_ID")
HB = os.environ.get("CTRL_HEARTBEAT", "/workspace/controller_heartbeat")
TOL = int(os.environ.get("DEADMAN_TOL_S", "600"))
POLL = int(os.environ.get("DEADMAN_POLL_S", "30"))
KILL_KEY = (os.environ.get("RUNPOD_KILL_KEY", "") or _pid1_env("RUNPOD_KILL_KEY")
            or os.environ.get("RUNPOD_API_KEY", "") or _pid1_env("RUNPOD_API_KEY"))
LOG = os.environ.get("DEADMAN_LOG", "/workspace/blade_capture/deadman.log")


def log(m):
    try:
        with open(LOG, "a") as f:
            f.write(f"{int(time.time())} {m}\n")
    except Exception:
        pass


def try_terminate():
    if POD_ID:
        try:
            r = subprocess.run(["runpodctl", "remove", "pod", POD_ID],
                               capture_output=True, text=True, timeout=40)
            log(f"runpodctl rc={r.returncode} out={r.stdout.strip()[:150]} err={r.stderr.strip()[:150]}")
            if r.returncode == 0:
                return "runpodctl"
        except Exception as e:
            log(f"runpodctl exc {e}")
    if KILL_KEY and POD_ID:
        url = f"https://rest.runpod.io/v1/pods/{POD_ID}"
        try:
            req = urllib.request.Request(url, method="DELETE",
                headers={"Authorization": f"Bearer {KILL_KEY}", "User-Agent": "curl/8.5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                log(f"REST status={resp.status}")
                return "rest"
        except Exception as e:
            log(f"REST exc {e}")
            rc = os.system(f'curl -s -X DELETE "{url}" -H "Authorization: Bearer {KILL_KEY}" '
                           f'-H "User-Agent: curl/8.5.0" >> {LOG} 2>&1')
            log(f"curl rc={rc}")
            return "curl" if rc == 0 else None
    return None


def main():
    # Report the RESOLVED key (what terminate actually uses), not just the direct env —
    # the key is normally injected into /proc/1/environ, absent from this process's env.
    log(f"deadman up POD_ID={POD_ID or 'MISSING'} TOL={TOL}s POLL={POLL}s HB={HB} "
        f"resolved_kill_key={bool(KILL_KEY)} kill_key_prefix={(KILL_KEY or '')[:4]} "
        f"(direct_env={bool(os.environ.get('RUNPOD_KILL_KEY'))} "
        f"pid1={bool(_pid1_env('RUNPOD_KILL_KEY'))})")
    while True:
        try:
            age = time.time() - os.path.getmtime(HB)
        except OSError:
            age = TOL + 1  # missing heartbeat = stale
        if age > TOL:
            log(f"HEARTBEAT STALE age={age:.0f}s > {TOL}s -> kill NAMD + self-terminate")
            os.system("pkill -9 namd3 2>/dev/null; pkill -9 -f nadoc_chain 2>/dev/null")
            m = try_terminate()
            log(f"terminate method={m}")
            sys.exit(0)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
