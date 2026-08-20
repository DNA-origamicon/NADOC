#!/usr/bin/env python
"""Repair a download partial whose HEAD is a live-frame stand-in DCD.

The old live-frame writer shared ``<dest>.part`` with the resumable downloader, so a
snapshot refresh truncated an in-flight partial to a single frame; the next fetch then
appended genuine remote bytes onto that foreign head.  Everything after the stand-in is
real data at the *correct* remote offset, because ``_stream_get`` always seeks to the
local file size — so the damage is confined to the first ``header + one frame`` bytes,
and the replacement is exactly the same length.  That makes the repair an in-place
overwrite of a few megabytes rather than a rewrite of the whole file.

Refuses to touch anything whose damage is not exactly this signature.

    # inspect (read-only)
    uv run python scripts/repair_dcd_partial.py --job-id 6950d3b79138

    # repair a quarantined partial and install it as the one to resume from
    uv run python scripts/repair_dcd_partial.py --job-id 6950d3b79138 \\
        --partial .../seg.dcd.part.rejected --promote --apply
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import cluster_ssh, resume_transfer  # noqa: E402
from backend.core.md_job import MdJob  # noqa: E402

_PARTIAL_SUFFIXES = (".rejected", ".part")


def _workspace() -> Path:
    return Path(os.environ.get("NADOC_WORKSPACE", "workspace")).resolve()


def strip_partial_suffixes(name: str) -> str:
    """``seg.dcd.part.rejected`` -> ``seg.dcd`` (the real file it is a partial of)."""
    for suffix in _PARTIAL_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def locate(job: MdJob, workspace: Path, explicit: str | None) -> tuple[Path, str]:
    """Resolve the partial to repair and the remote path it must be reconciled against."""
    pkg = job.package_dir(workspace)
    if explicit:
        part = Path(explicit).resolve()
        if not part.is_file():
            raise SystemExit(f"no such file: {part}")
    else:
        found = sorted((pkg / "output").glob("*.dcd.part"))
        if len(found) != 1:
            raise SystemExit(
                f"expected exactly one .dcd.part under {pkg / 'output'}, found "
                f"{len(found)} — pass --partial to choose one"
            )
        part = found[0]
    scratch = job.remote_scratch_dir
    if not scratch:
        raise SystemExit("job has no remote scratch dir")
    real = part.with_name(strip_partial_suffixes(part.name))
    try:
        rel = real.relative_to(pkg).as_posix()
    except ValueError:
        raise SystemExit(f"{part} is not inside the job package {pkg}") from None
    return part, f"{scratch}/{rel}"


def diagnose(part: Path, *, quiet: bool = False) -> int:
    """Return the corrupt-head length, or exit if this is not the known signature."""
    layout = resume_transfer.dcd_layout(part)
    if layout is None:
        raise SystemExit(f"{part} does not parse as a DCD at all — not this failure mode")
    head = layout.header_size + layout.frame_size
    ok, detail = resume_transfer.dcd_prefix_is_valid(part)
    if ok:
        raise SystemExit(
            f"{part.name} is already structurally sound ({detail}) — nothing to repair"
        )
    if f"at {head}" not in detail:
        raise SystemExit(
            f"{part} is damaged, but not with the stand-in-head signature.\n"
            f"  expected the first bad boundary at byte {head}\n"
            f"  actual: {detail}\n"
            "Refusing to guess. Re-download this file."
        )
    if not quiet:
        print(f"  layout      : header={layout.header_size} frame={layout.frame_size} "
              f"atoms={layout.n_atoms}")
        print(f"  diagnosis   : {detail}")
        print(f"  corrupt head: bytes [0, {head}) = one stand-in header + one stand-in frame")
        print(f"  intact tail : bytes [{head}, {part.stat().st_size}) = genuine remote data")
    return head


def promote(part: Path) -> Path:
    """Install a repaired quarantined partial as the active ``.part``."""
    if not part.name.endswith(".rejected"):
        return part
    active = part.with_name(part.name[: -len(".rejected")])
    if active.exists():
        # Shorter prefix of the same remote file, so it is redundant once the longer one
        # validates — but moved aside rather than deleted, and left for the user to drop.
        superseded = active.with_name(active.name + ".superseded")
        print(f"  existing partial ({active.stat().st_size:,} bytes) moved aside -> "
              f"{superseded.name}")
        os.replace(active, superseded)
    os.replace(part, active)
    resume_transfer.clear_sidecar(part)
    print(f"  promoted -> {active.name}")
    return active


async def repair(
    part: Path,
    remote_path: str,
    head: int,
    *,
    apply: bool,
    do_promote: bool,
    lock_path: Path,
) -> None:
    size = part.stat().st_size
    print(f"\nremote : {remote_path}")
    print(f"local  : {part}  ({size:,} bytes)")
    print(f"repair : overwrite {head:,} bytes in place at offset 0 "
          f"({head / size * 100:.4f}% of the file); {size - head:,} bytes preserved\n")
    if not apply:
        print("DRY RUN — re-run with --apply to perform the repair.")
        return

    # Take the lock BEFORE anything else: md_executor.fetch_outputs holds this same
    # exclusive flock for the whole of a download, so acquiring it is what stops a fetch
    # started from the connected app from appending while the head is rewritten.  Fail
    # here rather than after asking for a password.
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+b")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(
            f"another process holds {lock_path} — a download for this job is running.\n"
            "Stop it (or disconnect Alpine in the app) and re-run."
        ) from None
    print(f"holding the download lock ({lock_path.name}).")

    try:
        # Re-read the state now that nothing else can move it.  A download that appended
        # between the diagnosis and the lock would have shifted both size and verdict.
        size = part.stat().st_size
        if diagnose(part, quiet=True) != head:
            raise SystemExit("the partial changed under us; re-run the diagnosis")

        host = os.environ.get("NADOC_CLUSTER_HOST", "login.rc.colorado.edu")
        user = os.environ.get("NADOC_CLUSTER_USER") or input("Alpine username: ").strip()
        password = getpass.getpass("Alpine password: ")
        duo = os.environ.get("NADOC_DUO_METHOD", "push")

        conn = cluster_ssh.ClusterConnection()
        print(f"connecting to {host} as {user} (Duo: {duo}) …")
        await conn.connect(host, user, password, duo)
        print("connected.")
        try:
            raw = conn._require()  # noqa: SLF001 — one-off maintenance tool
            async with raw.start_sftp_client() as sftp:
                attrs = await sftp.stat(remote_path)
                remote_size = int(attrs.size)
                remote_mtime = getattr(attrs, "mtime", None)
                if remote_size < size:
                    raise SystemExit(
                        f"remote is {remote_size:,} bytes but the local partial is "
                        f"{size:,} — this partial is not from that file"
                    )
                print(f"remote size: {remote_size:,} bytes")
                print(f"fetching remote [0, {head:,}) …")
                buf = bytearray()
                async with sftp.open(remote_path, "rb") as rf:
                    while len(buf) < head:
                        chunk = await rf.read(min(1 << 20, head - len(buf)))
                        if not chunk:
                            break
                        buf.extend(chunk)
                        print(f"\r  {len(buf):,}/{head:,}", end="", flush=True)
                print()
                if len(buf) != head:
                    raise SystemExit(f"short read: got {len(buf)} of {head}")
        finally:
            await conn.disconnect()

        with open(part, "r+b") as fh:
            fh.seek(0)
            fh.write(bytes(buf))
            fh.flush()
            os.fsync(fh.fileno())
        print("head overwritten.")

        ok, detail = resume_transfer.dcd_prefix_is_valid(part)
        if not ok:
            raise SystemExit(f"STILL INVALID after repair: {detail}")
        print(f"VALIDATED: {detail}")
        if part.stat().st_size != size:
            raise SystemExit(
                f"file size changed during repair ({size} -> {part.stat().st_size})"
            )

        active = promote(part) if do_promote else part
        resume_transfer.write_sidecar(
            active, remote_path=remote_path, remote_size=remote_size,
            remote_mtime=remote_mtime, offset=size,
        )
        print(f"\nRepaired. {size:,} of {remote_size:,} bytes "
              f"({size / remote_size * 100:.1f}%) are now a verified prefix — resume the "
              "download to continue from here.")
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--partial", help="partial to repair (default: the job's *.dcd.part)")
    ap.add_argument("--promote", action="store_true",
                    help="after repair, install it as the active .part to resume from")
    ap.add_argument("--apply", action="store_true", help="perform it (default: dry run)")
    args = ap.parse_args()

    ws = _workspace()
    job = MdJob.load(args.job_id, ws)
    part, remote_path = locate(job, ws, args.partial)
    print(f"job {args.job_id}: {job.design_name}")
    head = diagnose(part)
    asyncio.run(
        repair(
            part, remote_path, head,
            apply=args.apply, do_promote=args.promote,
            lock_path=job.job_dir(ws) / ".download.lock",
        )
    )


if __name__ == "__main__":
    main()
