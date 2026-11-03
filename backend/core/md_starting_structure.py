"""Display-only snapshot of the coordinates a prepared NAMD job will start from.

Derived files stay outside output/: they must never count as simulation results.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

from backend.core.md_import import _read_namd_assignments, _resolve_relative

_LOCK = threading.Lock()


def starting_structure_display(manifest_path: Path) -> Path | None:
    """Return a cached display manifest, or None until the inputs are available."""
    data = json.loads(manifest_path.read_text())
    package = manifest_path.parent
    first = (data.get('minimization') or {}).get('name')
    if not first:
        stages = data.get('segments') or data.get('stages') or []
        first = stages[0].get('name') if stages else None
    if not first:
        return None
    conf = next((package / f'{first}{suffix}' for suffix in ('.conf', '.namd')
                 if (package / f'{first}{suffix}').is_file()), None)
    if conf is None:
        return None
    values = _read_namd_assignments(conf)
    topology = _resolve_relative(package, values.get('structure'))
    reference = _resolve_relative(package, values.get('coordinates'))
    # binCoordinates overrides coordinates in NAMD; never substitute the PDB
    # when the required inherited binary checkpoint is missing.
    source = _resolve_relative(package, values.get('bincoordinates')) or reference
    xsc = _resolve_relative(package, values.get('extendedsystem'))
    dependencies = [manifest_path, conf, topology, reference, source, *([xsc] if xsc else [])]
    if any(path is None or not path.is_file() for path in dependencies):
        return None
    signature = [(str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns) for p in dependencies]
    key = hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:20]
    cache = package / '.nadoc-analysis' / 'starting-structure' / key
    display = cache / 'display.json'
    with _LOCK:
        if display.is_file():
            return display
        from MDAnalysis.coordinates.DCD import DCDWriter
        from MDAnalysis.coordinates.NAMDBIN import NAMDBINReader
        from MDAnalysis.coordinates.PDB import PDBReader
        from backend.core.remote_live_frame import parse_xsc_dimensions

        dimensions = parse_xsc_dimensions(xsc.read_text()) if xsc else None
        if dimensions is None and data.get('box_ang'):
            dimensions = [*data['box_ang'], 90, 90, 90]
        reader_type = NAMDBINReader if values.get('bincoordinates') else PDBReader
        cache.mkdir(parents=True, exist_ok=True)
        with reader_type(str(source)) as reader:
            if dimensions is not None:
                reader.ts.dimensions = dimensions

            class Frame:
                ts = reader.ts

            temporary = cache / 'start.tmp.dcd'
            with DCDWriter(str(temporary), n_atoms=reader.n_atoms) as writer:
                writer.write(Frame())
            temporary.replace(cache / 'start.dcd')
        payload = {
            'package_dir': str(package.resolve()),
            'name_stem': data.get('name_stem'),
            'files': {'topology': str(topology.resolve()),
                      'coordinates': str(reference.resolve()), 'output_dir': str(cache.resolve())},
            'segments': [{'name': 'start'}],
        }
        temporary = cache / 'display.tmp.json'
        temporary.write_text(json.dumps(payload))
        temporary.replace(display)
    return display
