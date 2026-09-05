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


def graphene_pressure_conf(conf: str, *, enabled: bool) -> str:
    """Keep restrained-wall NPT coupling gentle across stage/process boundaries.

    Leave NVT and non-wall configurations unchanged, and retain already slower
    piston settings. This changes neither the ensemble nor the integration timestep.
    """
    if not enabled:
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
