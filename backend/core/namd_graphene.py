"""Force-field identity of NADOC's restrained graphene wall sites.

These are independently restrained wall sites, not a bonded/elastic graphene model.
Their solvent/solute LJ parameters match CHARMM CA, but their mutual LJ interaction
must be zero: the 1.42 A lattice spacing is far inside CA's nonbonded repulsive core.
Use a distinct atom type so the pair override cannot affect aromatic protein atoms.
"""

import json
import re
from pathlib import Path

GRAPHENE_ATOM_TYPE = "NGRC"
GRAPHENE_NONBONDED_MODEL = "restrained_wall_no_self_lj_v1"
GRAPHENE_PARAMS = (GRAPHENE_ATOM_TYPE, 0.0, 12.01100)

# A Cartesian restrained sheet strongly couples isotropic dilation to the restraint
# virial. small_plate (Slurm 32089399) diverged in 12 steps with 1000/500 fs, in
# both resident and offload modes. Its recovered predecessor used 10000/5000 fs.
GRAPHENE_PISTON_PERIOD_FS = 10000.0
GRAPHENE_PISTON_DECAY_FS = 5000.0


def graphene_pressure_conf(conf: str, *, enabled: bool, fixed_cell: bool = False) -> str:
    """Keep restrained-wall NPT coupling gentle across stage/process boundaries.

    Leave NVT and non-wall configurations unchanged, and retain already slower
    piston settings. This changes neither the ensemble nor the integration timestep.
    """
    if not enabled:
        return conf
    if fixed_cell:
        # Fixed Cartesian wall references cannot follow cell dilation. Preserve the
        # periodic seam by disabling every supported barostat, including overrides.
        for key in ("langevinPiston", "BerendsenPressure"):
            pattern = r"^\s*" + key + r"\s+[^\n]+"
            if re.search(pattern, conf, re.M | re.I):
                conf = re.sub(pattern, key + " off", conf, flags=re.M | re.I)
        return conf
    matches = re.findall(r"^\s*langevinPiston\s+(\S+)", conf, re.M | re.I)
    if not matches or matches[-1].lower() not in {"on", "yes", "true", "1"}:
        return conf
    for key, minimum in (
        ("langevinPistonPeriod", GRAPHENE_PISTON_PERIOD_FS),
        ("langevinPistonDecay", GRAPHENE_PISTON_DECAY_FS),
    ):
        pattern = r"^(\s*" + key + r"\s+)([^\s#]+)"
        values = re.findall(pattern, conf, re.M | re.I)
        if not values:
            raise ValueError("Restrained graphene NPT is missing " + key)
        conf = re.sub(
            pattern,
            lambda match: match[1] + f"{max(float(match[2]), minimum):.1f}",
            conf,
            flags=re.M | re.I,
        )
    return conf


def describe_graphene_wall(spec: dict) -> None:
    spec.update(
        atom_type=GRAPHENE_ATOM_TYPE,
        nonbonded_model=GRAPHENE_NONBONDED_MODEL,
        graphene_self_lj=False,
    )


def validate_graphene_wall_package(package: Path) -> None:
    """Reject legacy/deformed wall packages before allocating or resuming compute."""
    manifest_path = package / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text())
    spec = manifest.get("graphene_nanopore")
    if not spec:
        return
    remedy = (
        "Copy this job and press Run to rebuild and minimize the corrected wall. "
        "The old minimization/relaxation checkpoints were generated with the faulty "
        "wall force field and cannot be reused."
    )
    if spec.get("nonbonded_model") != GRAPHENE_NONBONDED_MODEL:
        raise ValueError(
            "Legacy graphene wall has spurious carbon-carbon LJ forces. " + remedy
        )

    # Validate the actual loaded supplementary parameters, not just the descriptor.
    param_path = package / "forcefield" / "par_np_thiol.prm"
    section = None
    lj_ok = pair_ok = False
    for line in param_path.read_text().splitlines():
        fields = line.split("!", 1)[0].split()
        if not fields or fields[0].startswith("*"):
            continue
        if fields[0].upper() in {"NONBONDED", "NBFIX", "END"}:
            section = fields[0].upper()
            continue
        if section == "NONBONDED" and fields[0] == GRAPHENE_ATOM_TYPE:
            lj_ok = (
                len(fields) >= 4
                and float(fields[2]) == -0.07
                and float(fields[3]) == 1.9924
            )
        if section == "NBFIX" and fields[:2] == [GRAPHENE_ATOM_TYPE] * 2:
            pair_ok = (
                len(fields) >= 6 and float(fields[2]) == 0 and float(fields[4]) == 0
            )
    if not (lj_ok and pair_ok):
        raise ValueError(
            "Graphene wall LJ parameters or self-pair override are missing. " + remedy
        )

    found = False
    for psf in package.glob("*.psf"):
        with psf.open() as stream:
            for line in stream:
                if "!NATOM" not in line:
                    continue
                for _ in range(int(line.split()[0])):
                    fields = next(stream, "").split()
                    if len(fields) < 8:
                        raise ValueError("Incomplete graphene wall PSF. " + remedy)
                    if fields[3] != "GRP":
                        continue
                    found = True
                    if fields[5] != GRAPHENE_ATOM_TYPE or float(fields[6]) != 0:
                        raise ValueError(
                            "Graphene wall PSF uses an unsafe atom type/charge. "
                            + remedy
                        )
                break
    if not found:
        raise ValueError(
            "Graphene wall package has no graphene sites in its PSF. " + remedy
        )


def tile_graphene_to_cell(pdb_text: str, box_nm, spec: dict, *, cell_vectors_nm=None) -> str:
    """Replace the finite seed sheet with a commensurate, periodic restrained wall.

    A rectangular four-site honeycomb cell repeats exactly across both tangential
    dimensions. At most half a lattice repeat of strain fits the requested box;
    no duplicate boundary atoms or unfilled padding strips are introduced.
    Coordinates and the aperture remain in the caller's Cartesian frame.
    """
    if cell_vectors_nm is not None:
        from backend.core.graphene_cell_frame import tile_in_cell_frame
        return tile_in_cell_frame(pdb_text, box_nm, spec, cell_vectors_nm)

    import numpy as np
    from backend.core.namd_solvate import _graphene_identity, _hetatm_record

    lengths = np.asarray(box_nm, dtype=float)
    normal = np.asarray(spec['dir'], dtype=float)
    axis = int(np.argmax(np.abs(normal)))
    if not np.isclose(abs(normal[axis]), 1.0) or not np.allclose(np.delete(normal, axis), 0):
        raise ValueError('Periodic graphene requires a Cartesian surface normal (±X, ±Y or ±Z).')
    tangents = [i for i in range(3) if i != axis]
    original = pdb_text.splitlines()
    old = [line for line in original if line.startswith('HETATM') and line[72:76].strip().startswith('GR')]
    if not old:
        raise ValueError('Periodic graphene has no seed wall sites')
    first = np.array([float(old[0][i:i + 8]) / 10 for i in (30, 38, 46)])
    from backend.core.surface_transforms import RigidTransform

    recenter = RigidTransform(
        translation_nm=first - np.array(spec.pop('_first_site_nm'))
    )
    from backend.core.surface_periodic import translate_coated_surface
    translate_coated_surface(spec, recenter.translation_nm)
    center = np.asarray(spec['pore_center_nm'])
    radius = float(spec.get('pore_diameter_nm', 2.1)) / 2
    if min(lengths[tangents]) <= 2 * radius + 0.6:
        raise ValueError('Graphene cell must leave at least 0.6 nm between periodic pore edges.')
    # Match the side/layer direction of the already deposited finite seed.
    levels = np.unique([round(float(line[30 + 8 * axis:38 + 8 * axis]) / 10, 4) for line in old])
    if levels.min() < 0 or levels.max() >= lengths[axis]:
        raise ValueError('Box normal dimension does not contain the graphene layers.')
    bond = 0.142
    repeats = np.maximum(1, np.rint(lengths[tangents] / [3 * bond, np.sqrt(3) * bond]).astype(int))
    periods = lengths[tangents] / repeats
    basis = [(0, 0), (1/3, 0), (1/2, 1/2), (5/6, 1/2)]
    atoms = []
    for level in levels:
        for i in range(repeats[0]):
            for j in range(repeats[1]):
                for a, b in basis:
                    lateral = (np.array([i + a, j + b]) * periods + center[tangents]) % lengths[tangents]
                    delta = lateral - center[tangents]
                    delta -= lengths[tangents] * np.rint(delta / lengths[tangents])
                    if np.dot(delta, delta) < radius * radius:
                        continue
                    xyz = center.copy()
                    xyz[tangents] = lateral
                    xyz[axis] = level
                    segid, resid = _graphene_identity(len(atoms))
                    atoms.append(_hetatm_record(len(atoms) + 1, 'C', 'GRP', 'G', resid,
                                                *(xyz * 10), segname=segid))
    spec.update(
        pore_center_nm=center.tolist(), plane_point_nm=center.tolist(),
        position_nm=float(center[axis]), periodic_boundary_model='commensurate_wall_v1',
        periodic_box_nm=lengths.tolist(), lattice_repeats=repeats.tolist(),
        lattice_scale=(periods / [3 * bond, np.sqrt(3) * bond]).tolist(),
        cell_policy='fixed_volume',
    )
    old_set = set(old)
    kept = [line for line in original if line not in old_set and line.strip() != 'END']
    return '\n'.join(kept + atoms + ['END', ''])
