"""Resolve MD run config files into trajectory files NADOC can stream."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MdTrajectorySource:
    config_path: Path
    package_dir: Path
    topology_path: Path
    coordinate_path: Path
    trajectory_path: Path
    log_path: Path | None = None
    name_stem: str | None = None
    stage_name: str | None = None
    dt_ps: float | None = None
    nstxout_comp: int | None = None
    ns_per_day: float | None = None
    temperature_k: float | None = None
    warnings: list[str] = field(default_factory=list)


_RE_ASSIGN = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s+(.+?)\s*(?:#.*)?$")


def _read_namd_assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(errors="replace").splitlines():
        m = _RE_ASSIGN.match(raw)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1].strip()
        values[key.lower()] = value
    return values


def _resolve_relative(base: Path, value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else (base / p).resolve()


def _manifest_file(package_dir: Path, files: dict, key: str) -> Path | None:
    value = files.get(key)
    if not isinstance(value, str) or not value:
        return None
    return _resolve_relative(package_dir, value)


def _parse_namd_metrics(log_path: Path | None, conf_path: Path | None = None) -> tuple[float | None, float | None, float | None, int | None]:
    ns_per_day = None
    temp = None
    dt_ps = None
    dcd_freq = None

    if conf_path and conf_path.exists():
        vals = _read_namd_assignments(conf_path)
        try:
            # NAMD timestep is in femtoseconds.
            dt_ps = float(vals.get("timestep", "")) / 1000.0
        except ValueError:
            pass
        try:
            dcd_freq = int(float(vals.get("dcdfreq", "")))
        except ValueError:
            pass

    if log_path and log_path.exists():
        for line in log_path.read_text(errors="replace").splitlines():
            if line.startswith("PERFORMANCE:"):
                parts = line.split()
                try:
                    ns_per_day = float(parts[3])
                except (IndexError, ValueError):
                    pass
            elif line.startswith("ENERGY:"):
                parts = line.split()
                try:
                    temp = float(parts[12])
                except (IndexError, ValueError):
                    pass
    return ns_per_day, temp, dt_ps, dcd_freq


def _first_existing(candidates: list[Path]) -> Path | None:
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None


def _latest_existing_dcd(package_dir: Path, stage_names: list[str], output_dir: Path | None = None) -> tuple[Path | None, str | None]:
    output = output_dir or package_dir / "output"
    for name in reversed(stage_names):
        dcd = output / f"{name}.dcd"
        if dcd.exists() and dcd.stat().st_size > 0:
            return dcd.resolve(), name
    dcds = sorted(output.glob("*.dcd"), key=lambda p: p.stat().st_mtime) if output.exists() else []
    if dcds:
        dcd = dcds[-1]
        return dcd.resolve(), dcd.stem
    return None, None


def resolve_md_config(config_path: str | Path) -> MdTrajectorySource:
    """Resolve a NAMD JSON manifest or .namd/.conf file into PSF/PDB/DCD paths."""
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Config file not found: {path}")

    warnings: list[str] = []

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(errors="replace"))
        package_dir = Path(data.get("package_dir") or path.parent).expanduser().resolve()
        name_stem = data.get("name_stem")
        files = data.get("files") if isinstance(data.get("files"), dict) else {}
        raw_stages = data.get("stages")
        if not isinstance(raw_stages, list):
            raw_stages = data.get("segments")
        stage_names = [s.get("name") for s in raw_stages or [] if isinstance(s, dict) and s.get("name")]
        output_dir = _manifest_file(package_dir, files, "output_dir") or package_dir / "output"
        if not name_stem:
            psfs = sorted(package_dir.glob("*.psf"))
            name_stem = psfs[0].stem if psfs else None

        topology = _first_existing([
            _manifest_file(package_dir, files, "topology") or package_dir / "__missing__.psf",
            package_dir / f"{name_stem}.psf" if name_stem else package_dir / "__missing__.psf",
            *sorted(package_dir.glob("*.psf")),
        ])
        coordinate = _first_existing([
            _manifest_file(package_dir, files, "coordinates") or package_dir / "__missing__.pdb",
            package_dir / f"{name_stem}.pdb" if name_stem else package_dir / "__missing__.pdb",
            *sorted(package_dir.glob("*.pdb")),
        ])
        trajectory, stage = _latest_existing_dcd(package_dir, stage_names, output_dir)
        conf = None
        if stage:
            conf = _first_existing([
                package_dir / f"{stage}.conf",
                package_dir / f"{stage}.namd",
            ])
        log = package_dir / f"{stage}.log" if stage else None

        if not topology:
            raise ValueError(f"No PSF found in {package_dir}")
        if not coordinate:
            raise ValueError(f"No PDB found in {package_dir}")
        if not trajectory:
            raise ValueError(f"No DCD trajectory found in {output_dir}")

        ns_day, temp, dt_ps, dcd_freq = _parse_namd_metrics(log if log and log.exists() else None, conf if conf and conf.exists() else None)
        return MdTrajectorySource(
            config_path=path,
            package_dir=package_dir,
            topology_path=topology,
            coordinate_path=coordinate,
            trajectory_path=trajectory,
            log_path=log if log and log.exists() else None,
            name_stem=name_stem,
            stage_name=stage,
            dt_ps=dt_ps,
            nstxout_comp=dcd_freq,
            ns_per_day=ns_day,
            temperature_k=temp,
            warnings=warnings,
        )

    if path.suffix.lower() in {".namd", ".conf"}:
        package_dir = path.parent
        vals = _read_namd_assignments(path)
        topology = _resolve_relative(package_dir, vals.get("structure"))
        coordinate = _resolve_relative(package_dir, vals.get("coordinates"))
        output_name = vals.get("outputname")
        dcd_file = vals.get("dcdfile")
        trajectory = _resolve_relative(package_dir, dcd_file)
        if trajectory is None and output_name:
            trajectory = _resolve_relative(package_dir, f"{output_name}.dcd")
        if trajectory is None or not trajectory.exists():
            out = package_dir / "output"
            candidates = sorted(out.glob(f"{path.stem}*.dcd")) if out.exists() else []
            if candidates:
                trajectory = candidates[-1].resolve()

        if coordinate is None or coordinate.suffix.lower() != ".pdb" or not coordinate.exists():
            stem = topology.stem if topology else path.stem
            coordinate = _first_existing([package_dir / f"{stem}.pdb", *sorted(package_dir.glob("*.pdb"))])
        log = package_dir / f"{path.stem}.log"

        if not topology or not topology.exists():
            raise ValueError(f"No PSF/structure found from {path.name}")
        if not coordinate or not coordinate.exists():
            raise ValueError(f"No PDB coordinates found next to {path.name}")
        if not trajectory or not trajectory.exists():
            raise ValueError(f"No DCD trajectory found from {path.name}")

        ns_day, temp, dt_ps, dcd_freq = _parse_namd_metrics(log if log.exists() else None, path)
        return MdTrajectorySource(
            config_path=path,
            package_dir=package_dir,
            topology_path=topology.resolve(),
            coordinate_path=coordinate.resolve(),
            trajectory_path=trajectory.resolve(),
            log_path=log.resolve() if log.exists() else None,
            name_stem=topology.stem,
            stage_name=path.stem,
            dt_ps=dt_ps,
            nstxout_comp=dcd_freq,
            ns_per_day=ns_day,
            temperature_k=temp,
            warnings=warnings,
        )

    raise ValueError(f"Unsupported MD config type: {path.suffix}")
