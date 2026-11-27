"""EXPERIMENTAL: native MagicDNA free-form build/reopen/replay development loop.

Local runs interfered with desktop use. Use an isolated graphical session.

No NADOC structures are authored. Run under `just validate-safe`. MATLAB needs
Java/Handle Graphics (this is unattended batch, not MATLAB -nojvm/-nodisplay).
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from backend.core.conversion_integrity import validate_cadnano_source
from tools.magicdna.routing import digest

HELPERS = Path(__file__).resolve().parent


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def native_path(path, windows):
    path = Path(path).resolve()
    if windows:
        return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
    return str(path)


def run_matlab(executable, expression, directory, timeout):
    """Bound each fresh process; on WSL timeout kill only its Windows PID tree."""
    directory.mkdir()
    windows = executable.suffix.lower() == ".exe" and os.name != "nt"
    script = directory / "run_native.m"
    script.write_text(expression + "\n")
    batch = "run(" + quote(native_path(script, windows)) + ")"
    if windows:
        powershell = shutil.which("powershell.exe")
        if not powershell:
            raise RuntimeError(
                "WSL requires powershell.exe for a scoped MATLAB watchdog"
            )
        ps = directory / "launch.ps1"
        ps.write_text(
            "$ErrorActionPreference='Stop'\n"
            "$p=Start-Process -FilePath "
            + quote(native_path(executable, True))
            + " -ArgumentList @('-batch', "
            + quote('"' + batch + '"')
            + ")"
            + " -PassThru -RedirectStandardOutput "
            + quote(native_path(directory / "stdout.log", True))
            + " -RedirectStandardError "
            + quote(native_path(directory / "stderr.log", True))
            + "\n$handle=$p.Handle\n$p.Id | Set-Content "
            + quote(native_path(directory / "windows.pid", True))
            + f"\nif (-not $p.WaitForExit({timeout * 1000})) {{\n"
            + "  & taskkill.exe /PID $p.Id /T /F\n  throw 'MATLAB_TIMEOUT'\n}\n"
            + "$p.Refresh()\nexit $p.ExitCode\n"
        )
        subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                native_path(ps, True),
            ],
            check=True,
        )
    else:
        with (directory / "stdout.log").open("w") as stream:
            process = subprocess.Popen(
                [str(executable), "-batch", batch],
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False
                    )
                else:
                    import signal

                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
            if process.returncode:
                raise RuntimeError(f"MATLAB failed: {directory}")


def graph_report(path):
    data = json.loads(path.read_text())
    validate_cadnano_source(data)
    hs = data["vstrands"]
    if not hs or len({(h["row"], h["col"]) for h in hs}) != len(hs):
        raise ValueError("Empty or duplicate-cell native routing")
    result = {"helices": len(hs), "routing_sha256": digest(data)}
    for kind in ("scaf", "stap"):
        nodes = {
            (h["num"], bp): e
            for h in hs
            for bp, e in enumerate(h[kind])
            if e != [-1] * 4
        }
        if not nodes:
            raise ValueError(f"Empty {kind} routing")
        seen, lengths, cycles = set(), [], 0
        starts = [p for p, e in nodes.items() if e[:2] == [-1, -1]]
        for start in starts + sorted(nodes):
            if start in seen:
                continue
            current, walk = start, set()
            while current != (-1, -1) and current not in walk:
                if current in seen:
                    raise ValueError("Merging strand walks")
                walk.add(current)
                current = tuple(nodes[current][2:])
            if current != (-1, -1):
                if current != start:
                    raise ValueError("Invalid strand cycle")
                cycles += 1
            seen.update(walk)
            lengths.append(len(walk))
        result[kind] = {
            "sites": len(nodes),
            "strands": len(lengths),
            "circular": cycles,
            "lengths_sites": sorted(lengths),
        }
    return result


def compare_builds(first, replay, suffix):
    """Exact deterministic replay; graph signature ignores only colors/padding/IDs."""
    a, b = (json.loads((p / "report.json").read_text()) for p in (first, replay))
    for field in (
        "bundle_geometry",
        "frames",
        "curve_points",
        "helix_count_per_bundle",
        "scaffolds",
        "staples",
    ):
        if a[field] != b[field]:
            raise ValueError(f"Independent recipe replay changed {field}")
    if (first / "process.json").read_text() != (replay / "process.json").read_text():
        raise ValueError("Independent replay changed recorded operations")
    ga, gb = (graph_report(p / f"routing{suffix}.json") for p in (first, replay))
    if ga != gb:
        raise ValueError("Independent replay changed routing/indels")
    return ga


def manifest(source):
    paths = (
        sorted(source.rglob("*.m"))
        + sorted(source.rglob("CadNano.json"))
        + [source / "Previous Mechanism/Hinge.mat"]
    )
    return {
        str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experimental",
        action="store_true",
        required=True,
        help="Acknowledge experimental desktop-interfering MATLAB execution",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--matlab", type=Path, default=os.environ.get("MAGICDNA_MATLAB")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--case", choices=["curved_6hb", "curved_3x6", "both"], default="both"
    )
    args = parser.parse_args()
    if args.matlab is None:
        parser.error("Pass --matlab or set MAGICDNA_MATLAB")
    source, executable, output = (
        p.resolve() for p in (args.source, args.matlab, args.output)
    )
    if not executable.is_file() or not source.is_dir() or args.timeout <= 0:
        parser.error("Source, MATLAB executable and positive timeout required")
    output.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(output).free < 512 * 1024**2:
        raise RuntimeError("Require at least 512 MiB free development storage")
    from tools.magicdna.prepare_matlab import patch_source as patch_io
    from tools.magicdna.prepare_freeform import patch_source as patch_freeform

    patches = {"io": patch_io(source), "freeform": patch_freeform(source)}
    (output / "patches.json").write_text(json.dumps(patches, indent=2))
    sources = manifest(source)
    (output / "source_hashes.json").write_text(json.dumps(sources, indent=2))
    (output / "harness_hashes.json").write_text(
        json.dumps(
            {
                str(p.relative_to(HELPERS)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(HELPERS.rglob("*"))
                if p.suffix in (".py", ".m", ".json")
            },
            indent=2,
        )
    )
    windows = executable.suffix.lower() == ".exe" and os.name != "nt"
    arg = lambda p: quote(native_path(p, windows))
    prefix = "addpath(" + arg(HELPERS / "matlab") + "); "
    cases = ["curved_6hb", "curved_3x6"] if args.case == "both" else [args.case]
    reports = {}
    for case in cases:
        case_dir = output / case
        case_dir.mkdir()
        recipe = case_dir / "recipe.json"
        shutil.copyfile(HELPERS / "recipes" / (case + ".json"), recipe)
        suffix = "HC" if case == "curved_6hb" else "SQ"
        for stage in ("build", "reopen", "replay"):
            print(f"MAGICDNA_START {case} {stage}", flush=True)
            function = (
                "magicdna_freeform_reopen"
                if stage == "reopen"
                else "magicdna_freeform_build"
            )
            input_path = case_dir / "build" if stage == "reopen" else recipe
            expression = (
                prefix
                + function
                + "("
                + ",".join(map(arg, [source, input_path, case_dir / stage]))
                + ");"
            )
            run_matlab(
                executable, expression, case_dir / (stage + "_process"), args.timeout
            )
            graph_report(case_dir / stage / f"routing{suffix}.json")
            print(f"MAGICDNA_PASS {case} {stage}", flush=True)
        graph = compare_builds(case_dir / "build", case_dir / "replay", suffix)
        if graph != graph_report(case_dir / "reopen" / f"routing{suffix}.json"):
            raise ValueError("Native reopen changed exported routing")
        reopened = json.loads((case_dir / "reopen/report.json").read_text())
        reports[case] = {"graph": graph, "replay_exact": True, "reopen": reopened}
    if manifest(source) != sources:
        raise RuntimeError("MagicDNA source changed during run")
    (output / "verified.json").write_text(json.dumps(reports, indent=2))
    print("MAGICDNA_CLOSED_LOOP_PASS " + str(output), flush=True)


if __name__ == "__main__":
    main()
