#!/usr/bin/env python
"""Diagnose NADOC MD chain runs — why did a chain halt, and what do I do about it.

The command-line counterpart to the "Chain Simulations" sidebar: it reads the persisted
chain runs (``<workspace>/md_chains/*/chain.json``) that the MD supervisor drives, and
for each explains — in plain language — its status, which stage failed, WHY, and the
concrete next action. It reuses the exact same brain the UI can surface
(:func:`backend.core.md_chain_executor.diagnose_chain`), so terminal and app never
disagree.

Two failure shapes are told apart:

* a **spawn** failure — the stage never got a job (a 409 design-mismatch, a missing seed
  checkpoint, …). The reason is in ``chain.error`` and gets classified to a fix.
* a **job** failure — the stage's job ran and crashed. The doctor loads that oxDNA/NAMD
  job, prints its ``error``, and tails the newest ``*.log`` under its job dir.

Run::

    uv run python scripts/chain_doctor.py                 # summary of every chain
    uv run python scripts/chain_doctor.py --failed        # only failed chains, deep-dive
    uv run python scripts/chain_doctor.py <chain_id>      # deep-dive one chain
    uv run python scripts/chain_doctor.py latest          # deep-dive the newest chain
    uv run python scripts/chain_doctor.py --log-lines 40  # longer log tails

Workspace defaults to ``$NADOC_WORKSPACE`` (else ``./workspace``); override with
``--workspace PATH``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running as a bare script without -m.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import md_chain_executor as ce  # noqa: E402

_OK = "\033[32m✓\033[0m"
_WARN = "\033[33m!\033[0m"
_BAD = "\033[31m✗\033[0m"
_DIM = "\033[2m"
_R = "\033[0m"

_STATUS_MARK = {
    ce.CHAIN_COMPLETED: _OK,
    ce.CHAIN_FAILED: _BAD,
    ce.CHAIN_RUNNING: _WARN,
    ce.CHAIN_PENDING: _DIM + "·" + _R,
}
_STAGE_GLYPH = {
    ce.STAGE_DONE: _OK,
    ce.STAGE_FAILED: _BAD,
    ce.STAGE_RUNNING: _WARN,
    ce.STAGE_PENDING: _DIM + "○" + _R,
}


def _workspace(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    return Path(os.environ.get("NADOC_WORKSPACE", "workspace"))


def _chain_mtime(workspace: Path, chain_id: str) -> float:
    try:
        return ce.chain_path(workspace, chain_id).stat().st_mtime
    except OSError:
        return 0.0


def _tail_job_log(workspace: Path, engine: str, job_id: str, n_lines: int) -> None:
    """Load a realised stage job and print its error + the tail of its newest log."""
    try:
        if engine == "oxdna":
            from backend.core.oxdna_job import OxdnaJob
            job = OxdnaJob.load(job_id, workspace)
            status, error = job.status.value, job.error
        else:
            from backend.core.md_job import MdJob
            job = MdJob.load(job_id, workspace)
            status = getattr(job.status, "value", str(job.status))
            error = job.error
    except Exception as exc:  # noqa: BLE001 — a missing/torn job dir is itself a finding
        print(f"      {_WARN} could not load {engine} job {job_id}: {exc}")
        return

    print(f"      job {job_id}: status={status}"
          + (f"  error={error}" if error else ""))
    try:
        job_dir = job.job_dir(workspace)
    except Exception:  # noqa: BLE001
        return
    logs = sorted(job_dir.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        print(f"      {_DIM}(no *.log under {job_dir}){_R}")
        return
    log = logs[0]
    lines = log.read_text(errors="replace").splitlines()
    print(f"      {_DIM}tail of {log.relative_to(workspace)} "
          f"(last {min(n_lines, len(lines))} of {len(lines)} lines):{_R}")
    for ln in lines[-n_lines:]:
        print(f"        {_DIM}{ln}{_R}")


def _deep_dive(workspace: Path, chain: ce.ChainRun, n_lines: int) -> None:
    dx = ce.diagnose_chain(chain)
    mark = _STATUS_MARK.get(chain.status, "?")
    print(f"\n{mark} chain {chain.chain_id}  [{chain.status}]")
    print(f"    {dx['headline']}")

    # Per-stage table. The plan carries the label + design_source_path.
    for st in chain.stages:
        plan = chain.plan[st.index] if st.index < len(chain.plan) else None
        label = getattr(plan, "label", None) or f"{st.engine} {st.stage_id}"
        glyph = _STAGE_GLYPH.get(st.status, "?")
        jid = f"  job={st.job_id}" if st.job_id else ""
        print(f"    {glyph} stage {st.index}: {label}  ({st.status}){jid}")

    if chain.status == ce.CHAIN_FAILED:
        print(f"\n    {_BAD} why: {dx['cause']}")
        if dx["error"]:
            print(f"    {_DIM}raw: {dx['error']}{_R}")
        print(f"    → {dx['action']}")
        # Root design for the "open the right design" action.
        src = next((getattr(p, "design_source_path", None) for p in chain.plan
                    if getattr(p, "design_source_path", None)), None)
        if src:
            print(f"    {_DIM}this chain was built from: {src}{_R}")
        # If the failed stage DID spawn a job, tail its log.
        if dx["failed_job_id"] and dx["failed_index"] is not None:
            _tail_job_log(workspace, chain.stages[dx["failed_index"]].engine,
                          dx["failed_job_id"], n_lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chain", nargs="?", help="a chain id, or 'latest'")
    ap.add_argument("--workspace", help="workspace dir (default $NADOC_WORKSPACE or ./workspace)")
    ap.add_argument("--failed", action="store_true", help="deep-dive only failed chains")
    ap.add_argument("--log-lines", type=int, default=20, help="log tail length (default 20)")
    args = ap.parse_args()

    workspace = _workspace(args.workspace)
    chains = ce.list_chains(workspace)
    if not chains:
        print(f"{_WARN} No chains under {workspace / 'md_chains'} "
              "(is --workspace right? has a chain been launched?)")
        return 0

    # Newest first (mtime of chain.json) — the "latest" everyone means.
    chains.sort(key=lambda c: _chain_mtime(workspace, c.chain_id), reverse=True)

    # Selection.
    if args.chain == "latest":
        targets = chains[:1]
    elif args.chain:
        targets = [c for c in chains if c.chain_id.startswith(args.chain)]
        if not targets:
            print(f"{_BAD} No chain matching {args.chain!r}. Known: "
                  + ", ".join(c.chain_id for c in chains))
            return 1
    elif args.failed:
        targets = [c for c in chains if c.status == ce.CHAIN_FAILED]
        if not targets:
            print(f"{_OK} No failed chains among {len(chains)}.")
            return 0
    else:
        # No selector: one-line summary of every chain, then deep-dive the failed ones.
        print(f"Chains under {workspace / 'md_chains'}  ({len(chains)} total, newest first)")
        print("=" * 70)
        n_failed = 0
        for c in chains:
            dx = ce.diagnose_chain(c)
            mark = _STATUS_MARK.get(c.status, "?")
            print(f"{mark} {c.chain_id}  {dx['headline']}")
            n_failed += c.status == ce.CHAIN_FAILED
        if n_failed:
            print(f"\n{_BAD} {n_failed} failed — diagnosing:")
            targets = [c for c in chains if c.status == ce.CHAIN_FAILED]
        else:
            return 0

    for c in targets:
        _deep_dive(workspace, c, args.log_lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
