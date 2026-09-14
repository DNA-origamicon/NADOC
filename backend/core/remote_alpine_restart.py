"""Alpine execution journal and checkpoint continuation (stdlib, Python >=3.6).

Staged as nadoc_alpine_restart.py. Runs before NAMD can overwrite any output.
An allocation restart never silently repeats an interrupted stage from its seed.
"""

import argparse
import json
import math
import os
import re
import shutil
import struct
import time
from pathlib import Path


def restart_step_of(text):
    rows = [
        r.split()
        for r in text.splitlines()
        if r.strip() and not r.lstrip().startswith("#")
    ]
    return int(rows[-1][0])


JOURNAL = "output/nadoc_attempts.json"


def atomic_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def directive(text, key):
    matches = re.findall(r"^\s*" + key + r"\s+([^#\n]+)", text, re.M | re.I)
    return matches[-1].strip() if matches else None


def begin(package):
    path = package / JOURNAL
    path.parent.mkdir(exist_ok=True)
    journal = (
        json.loads(path.read_text())
        if path.exists()
        else {"version": 1, "attempts": []}
    )
    jid = os.environ.get("SLURM_JOB_ID", "manual")
    count = int(os.environ.get("SLURM_RESTART_COUNT", "0"))
    ident = "%s-r%d-%d" % (
        jid,
        count,
        time.time_ns() if hasattr(time, "time_ns") else int(time.time() * 1e9),
    )
    folder = package / "output" / "attempts" / ident
    folder.mkdir(parents=True)
    # Logs are small, and unlike a DCD they are redirected/truncated by the shell.
    for source in package.glob("*.log"):
        shutil.copy2(str(source), str(folder / source.name))
    journal["attempts"].append(
        dict(
            id=ident,
            slurm_job_id=jid,
            restart_count=count,
            started_at=time.time(),
            segments=[],
        )
    )
    atomic_json(path, journal)
    return ident


def checkpoint(package, segment, suffix="", expected_atoms=None):
    """Reject incomplete writes, mismatched pairs, and a not-yet-committed XSC.

    NAMD writes XSC, then coordinates, then velocities (verified against the live
    NAMD log). An outage between writes violates that ordering; neither it nor a mixed
    .old generation is safe. Validation is conservative; no seed fallback.
    """
    base = package / "output" / (segment + ".restart")
    paths = {
        ext: Path(str(base) + "." + ext + suffix) for ext in ("coor", "vel", "xsc")
    }
    stats = {ext: p.stat() for ext, p in paths.items()}
    counts = []
    for ext in ("coor", "vel"):
        with paths[ext].open("rb") as stream:
            raw = stream.read(4)
        if len(raw) != 4:
            raise ValueError("truncated checkpoint " + ext)
        count = struct.unpack("<i", raw)[0]
        if count <= 0 or stats[ext].st_size != 4 + 24 * count:
            raise ValueError("incomplete checkpoint " + ext)
        counts.append(count)
    if counts[0] != counts[1] or (expected_atoms and counts[0] != expected_atoms):
        raise ValueError(
            "checkpoint atom counts differ from each other or the structure"
        )
    xsc = paths["xsc"].read_text()
    row = [
        r.split()
        for r in xsc.splitlines()
        if r.strip() and not r.lstrip().startswith("#")
    ][-1]
    vals = [float(v) for v in row]
    if len(vals) < 13 or not all(math.isfinite(v) for v in vals):
        raise ValueError("invalid checkpoint cell")
    a, b, c = vals[1:4], vals[4:7], vals[7:10]
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if determinant <= 0:
        raise ValueError("invalid checkpoint cell volume")
    if (
        not stats["xsc"].st_mtime_ns
        <= stats["coor"].st_mtime_ns
        <= stats["vel"].st_mtime_ns
    ):
        raise ValueError(
            "checkpoint write ordering is inconsistent; generation is incomplete"
        )
    return restart_step_of(xsc), paths


def trim_to_checkpoint(package, segment, step, folder):
    """Keep the canonical trajectory chain nonoverlapping, retaining original bytes.

    A .old checkpoint can lag the last DCD write. Copies are needed ONLY for a
    truncated/overlapping piece; healthy aligned trajectories are never copied.
    """
    changes = []
    pattern = re.compile(re.escape(segment) + r"(?:\.cont[0-9]+)?\.dcd$")
    for path in sorted((package / "output").glob(segment + "*.dcd")):
        if not pattern.fullmatch(path.name):
            continue
        with path.open("rb") as stream:
            if stream.read(8) != struct.pack("<i", 84) + b"CORD":
                raise ValueError("cannot verify interrupted DCD " + path.name)
            controls = struct.unpack("<20i", stream.read(80))
            if stream.read(4) != struct.pack("<i", 84):
                raise ValueError("invalid DCD header marker")
            title = struct.unpack("<i", stream.read(4))[0]
            stream.seek(title + 4, 1)
            if struct.unpack("<i", stream.read(4))[0] != 4:
                raise ValueError("invalid DCD atom marker")
            atoms = struct.unpack("<i", stream.read(4))[0]
            stream.read(4)
            offset = stream.tell()
            if atoms <= 0 or controls[2] <= 0 or controls[8] or controls[11]:
                raise ValueError("unsupported interrupted DCD layout")
            frame_bytes = (56 if controls[10] else 0) + 3 * (8 + 4 * atoms)
            frames, extra = divmod(path.stat().st_size - offset, frame_bytes)
            keep = max(0, min(frames, (step - controls[1]) // controls[2] + 1))
            if keep:
                stream.seek(offset + (keep - 1) * frame_bytes)
                for size in ([48] if controls[10] else []) + [4 * atoms] * 3:
                    if struct.unpack("<i", stream.read(4))[0] != size:
                        raise ValueError("invalid last complete DCD frame")
                    stream.seek(size, 1)
                    if struct.unpack("<i", stream.read(4))[0] != size:
                        raise ValueError("invalid last complete DCD frame end")
        if keep == frames and not extra and controls[0] == frames:
            continue
        archive = folder / (path.name + ".original")
        if keep == 0:
            # Rename retains the full source and removes this empty piece from the
            # canonical chain. No user data is deleted.
            path.rename(archive)
        else:
            if not archive.exists():
                os.link(str(path), str(archive))
            tmp = path.with_name(path.name + ".repairing")
            limit = offset + keep * frame_bytes
            with path.open("rb") as src, tmp.open("wb") as dst:
                remaining = limit
                while remaining:
                    data = src.read(min(16 * 1024 * 1024, remaining))
                    if not data:
                        raise ValueError("interrupted DCD changed during preservation")
                    dst.write(data)
                    remaining -= len(data)
                dst.seek(8)
                dst.write(struct.pack("<i", keep))
                dst.seek(20)
                dst.write(struct.pack("<i", controls[1] + (keep - 1) * controls[2]))
            tmp.replace(path)
        changes.append(
            dict(
                file=path.name,
                kept_frames=keep,
                archived_original=str(archive.relative_to(package)),
            )
        )
    # XST is cheap to preserve and trim, and must obey the same checkpoint boundary.
    for path in (package / "output").glob(segment + "*.xst"):
        rows = path.read_text().splitlines(True)
        kept = [
            r
            for r in rows
            if not r.strip() or r.lstrip().startswith("#") or int(r.split()[0]) <= step
        ]
        if kept != rows:
            shutil.copy2(str(path), str(folder / (path.name + ".original")))
            tmp = path.with_name(path.name + ".repairing")
            tmp.write_text("".join(kept))
            tmp.replace(path)
    return changes


def prepare(package, segment, source, total):
    try:
        from nadoc_resume_conf import build_resume_conf
    except ImportError:
        from backend.core.remote_resume_conf import build_resume_conf
    path = package / JOURNAL
    journal = json.loads(path.read_text())
    attempt = journal["attempts"][-1]
    record = dict(segment=segment, mode="fresh", checkpoint_step=0)
    attempt["segments"].append(record)
    saved_logs = list(
        (package / "output" / "attempts" / attempt["id"]).glob(segment + "*.log")
    )
    for log in sorted(saved_logs, key=lambda p: p.stat().st_mtime, reverse=True):
        matches = re.findall(
            r"Configuration file is ([A-Za-z0-9_.-]+)\.conf", log.read_text()
        )
        if (
            matches
            and matches[-1].endswith((".cell_retry", ".alpine_resume"))
            and (package / (matches[-1] + ".conf")).exists()
        ):
            source = matches[-1]
            break
    original = (package / (source + ".conf")).read_text()
    if original.startswith("# NADOC_ALPINE_RESTART_GUARD_V1"):
        source = segment + ".before_restart_guard"
        original = (package / (source + ".conf")).read_text()
    out = package / "output"
    evidence = list(out.glob(segment + ".restart.*")) + list(
        out.glob(segment + "*.dcd")
    )
    # A log is evidence of a previous invocation even when no checkpoint was saved.
    evidence += list((out / "attempts" / attempt["id"]).glob(segment + "*.log"))
    try:
        previously_started = any(
            s.get("segment") == segment
            for a in journal["attempts"][:-1]
            for s in a.get("segments", [])
        )
        if not evidence and previously_started:
            raise ValueError(
                "previously started stage has no surviving output; explicit review required"
            )
        if not evidence:
            record["source_conf"] = source
            return source
        if (
            total <= 0
            or directive(original, "minimize")
            or "# NADOC_ADAPTIVE_MIN_BEGIN" in original
        ):
            raise ValueError("interrupted minimization requires explicit review")
        structure = directive(original, "structure")
        atoms = None
        if structure:
            with (package / structure).open() as stream:
                for line in stream:
                    if "!NATOM" in line:
                        atoms = int(line.split()[0])
                        break
        candidates = []
        for suffix in ("", ".old"):
            try:
                step, paths = checkpoint(package, segment, suffix, atoms)
                if 0 < step <= total:
                    candidates.append((step, suffix, paths))
            except (OSError, ValueError, IndexError, struct.error):
                pass
        if not candidates:
            raise ValueError(
                "no complete, consistent coordinate/velocity/cell checkpoint"
            )
        step, suffix, paths = max(candidates, key=lambda c: c[0])
        folder = out / "attempts" / attempt["id"] / segment
        folder.mkdir(parents=True, exist_ok=True)
        for ext, src in paths.items():
            shutil.copy2(str(src), str(folder / ("input." + ext)))
        record["trajectory_repairs"] = trim_to_checkpoint(
            package, segment, step, folder
        )
        # The immutable copy is the actual restart input, so rolling checkpoints
        # written during this attempt cannot destroy its provenance.
        text = build_resume_conf(original, segment, step, max(total, step + 1))
        if step == total:
            text = re.sub(r"^run\s+\d+\s*$", "run 0", text, flags=re.M)
        for ext, key in [
            ("coor", "binCoordinates"),
            ("vel", "binVelocities"),
            ("xsc", "extendedSystem"),
        ]:
            text = re.sub(
                r"^" + key + r"\s+[^\n]+",
                key + " " + str((folder / ("input." + ext)).relative_to(package)),
                text,
                flags=re.M,
            )
        index = 1
        while any(out.glob(segment + ".cont%d.*" % index)):
            index += 1
        for key, ext in [("dcdFile", "dcd"), ("xstFile", "xst")]:
            text = re.sub(
                r"^" + key + r"\s+[^\n]+",
                key + " output/" + segment + ".cont%d." % index + ext,
                text,
                flags=re.M,
            )
        # Auxiliary velocity/force trajectories must not be overwritten either.
        for key in ("velDCDfile", "forceDCDfile"):
            if directive(text, key):
                text = re.sub(
                    r"^\s*" + key + r"\s+[^\n]+",
                    key + " output/" + segment + ".cont%d." % index + key + ".dcd",
                    text,
                    flags=re.M | re.I,
                )
        target = segment + ".alpine_resume"
        (package / (target + ".conf")).write_text(text)
        record.update(
            mode="continued",
            checkpoint_step=step,
            checkpoint_generation=suffix or "current",
            source_conf=source,
            continuation_index=index,
            input_directory=str(folder.relative_to(package)),
            timestep_fs=float(directive(original, "timestep") or 0),
        )
        return target
    except Exception as exc:
        record.update(mode="blocked", error=str(exc))
        raise
    finally:
        atomic_json(path, journal)


def inspect_legacy(package, ident):
    """Preserve NAMD's one-generation backups without copying hundred-GB files."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", ident):
        raise ValueError("invalid incident identifier")
    package = package.resolve()
    destination = package / "output" / "attempts" / ident
    destination.mkdir(parents=True, exist_ok=True)
    saved = destination / "legacy.json"
    if saved.exists():
        return json.loads(saved.read_text())
    records = []
    for path in sorted((package / "output").glob("*.dcd.BAK")):
        segment = path.name[:-8]
        target = destination / "output" / (segment + ".dcd")
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            os.link(str(path), str(target))
        with target.open("rb") as stream:
            n = struct.unpack("<i", stream.read(4))[0]
            header = stream.read(n)
            if (
                n != 84
                or header[:4] != b"CORD"
                or struct.unpack("<i", stream.read(4))[0] != 84
            ):
                raise ValueError("unsupported DCD header")
            control = struct.unpack("<20i", header[4:])
            title_size = struct.unpack("<i", stream.read(4))[0]
            stream.seek(title_size + 4, 1)
            if struct.unpack("<i", stream.read(4))[0] != 4:
                raise ValueError("invalid atom record")
            atoms = struct.unpack("<i", stream.read(4))[0]
            stream.read(4)
            offset = stream.tell()
            frame_bytes = (56 if control[10] else 0) + 3 * (8 + 4 * atoms)
            if atoms <= 0 or control[8] or control[11]:
                raise ValueError("unsupported DCD layout")
            frames, trailing = divmod(target.stat().st_size - offset, frame_bytes)
            if frames <= 0 or trailing or frames != control[0]:
                raise ValueError("backup DCD incomplete; retain for manual recovery")
            stream.seek(offset + (frames - 1) * frame_bytes)
            for size in ([48] if control[10] else []) + [4 * atoms] * 3:
                if struct.unpack("<i", stream.read(4))[0] != size:
                    raise ValueError("invalid last-frame marker")
                stream.seek(size, 1)
                if struct.unpack("<i", stream.read(4))[0] != size:
                    raise ValueError("invalid last-frame end marker")
        xst = package / "output" / (segment + ".xst.BAK")
        if xst.exists() and not (target.parent / (segment + ".xst")).exists():
            os.link(str(xst), str(target.parent / (segment + ".xst")))
        conf = (package / (segment + ".conf")).read_text()
        records.append(
            dict(
                segment=segment,
                frames=frames,
                step=control[1] + (frames - 1) * control[2],
                timestep_fs=float(directive(conf, "timestep") or 0),
                size_bytes=target.stat().st_size,
                path=str(target),
            )
        )
    result = dict(
        id=ident,
        records=records,
        remote_directory=str(destination),
        protected=bool(records),
        checkpoint_available=False,
    )
    if records:
        atomic_json(saved, result)
    return result


def install_guard(package, segment):
    """Retrofit a running legacy job without altering Slurm or its running process.

    Atomic rename leaves the current process's opened config inode intact. The
    next invocation through Slurm's already-spooled script reads this Tcl wrapper.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        raise ValueError("unsupported segment name")
    path = package / (segment + ".conf")
    original = path.read_text()
    marker = "# NADOC_ALPINE_RESTART_GUARD_V1"
    if original.startswith(marker):
        return {"installed": True, "already_installed": True}
    if not directive(original, "run") or directive(original, "minimize"):
        raise ValueError("guard installation is limited to dynamics configurations")
    total = int(directive(original, "run")) + int(
        directive(original, "firsttimestep") or 0
    )
    source = segment + ".before_restart_guard"
    backup = package / (source + ".conf")
    if backup.exists() and backup.read_text() != original:
        raise ValueError("existing guard backup differs; refusing to replace it")
    if not backup.exists():
        backup.write_text(original)
    # Capture the old log now; the legacy shell redirects it before Tcl can run.
    log = package / (segment + ".log")
    backup_log = package / "output" / (segment + ".before_restart_guard.log")
    if log.exists() and not backup_log.exists():
        shutil.copy2(str(log), str(backup_log))
    text = (
        marker
        + "\n"
        + (
            "exec python3 nadoc_alpine_restart.py begin\n"
            "set nadoc_resume_config [exec python3 nadoc_alpine_restart.py prepare --segment %s --source %s --total %d]\n"
            'source "${nadoc_resume_config}.conf"\n'
        )
        % (segment, source, total)
    )
    tmp = path.with_name(path.name + ".installing")
    tmp.write_text(text)
    tmp.replace(path)
    return {
        "installed": True,
        "source": str(backup),
        "total_steps": total,
        "note": "Applies on the next NAMD invocation; current process is unchanged",
    }


def latest_dcd(package, segment):
    candidates = []
    for path in (package / "output").glob(segment + ".cont*.dcd"):
        match = re.fullmatch(re.escape(segment) + r"\.cont([0-9]+)\.dcd", path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    return str(
        max(candidates)[1] if candidates else package / "output" / (segment + ".dcd")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["begin", "prepare", "inspect", "install", "latest"]
    )
    parser.add_argument("--id")
    parser.add_argument("--segment")
    parser.add_argument("--source")
    parser.add_argument("--total", type=int, default=0)
    args = parser.parse_args()
    package = Path(".")
    if args.action == "begin":
        print(begin(package))
    elif args.action == "latest":
        print(latest_dcd(package, args.segment))
    elif args.action == "install":
        print(json.dumps(install_guard(package, args.segment)))
    elif args.action == "inspect":
        print(json.dumps(inspect_legacy(package, args.id)))
    else:
        print(prepare(package, args.segment, args.source, args.total))


if __name__ == "__main__":
    main()
