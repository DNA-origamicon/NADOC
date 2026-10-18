"""Explicit provisional simulation support for the reviewed six-residue CPDs.

This adapter does not change the photoproduct registry's scientific release gates.
Each package uses one isomer: the provisional CX atom types are not mixable.
"""

import hashlib
import json
import os
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.cpd_forcefield import CpdCapabilityError
from backend.core.cpd_six_residue import METHOD, SEEDS
from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)

ROOT = Path(__file__).resolve().parents[1] / "data/forcefield"
MANIFEST = ROOT / "mvp_cpds/manifest.json"


def uses_mvp(design):
    return any(p.orientation_method == METHOD for p in design.photoproduct_junctions)


def manifest():
    try:
        data = json.loads(MANIFEST.read_text())
    except (OSError, ValueError) as exc:
        raise CpdCapabilityError(
            f"Provisional CPD simulation manifest is unavailable: {exc}"
        ) from exc
    if data.get("schema") != "nadoc.experimental-cpd-simulation.v1":
        raise CpdCapabilityError("Unsupported provisional CPD simulation manifest")
    return data


def package_assets(design):
    data = manifest()
    isomers = {p.stereochemistry for p in design.photoproduct_junctions}
    if len(isomers) != 1 or any(
        p.orientation_method != METHOD for p in design.photoproduct_junctions
    ):
        raise CpdCapabilityError(
            "Provisional CPD simulation requires one isomer parameter set per system; mixed isomers/placements are unsupported."
        )
    stereo = next(iter(isomers))
    entry = next((p for p in data["products"] if p["stereochemistry"] == stereo), None)
    if entry is None:
        raise CpdCapabilityError(f"No provisional CPD simulation assets for {stereo}")
    parent = data["cgenff_parent"]
    source = Path(os.environ.get("NADOC_CGENFF_PARAMETERS", parent["source_path"]))
    if (
        not source.is_file()
        or hashlib.sha256(source.read_bytes()).hexdigest() != parent["sha256"]
    ):
        raise CpdCapabilityError(
            "Provisional CPD simulation needs the pinned CHARMM CGenFF parent parameters. Install the reviewed par_all36_cgenff.prm or set NADOC_CGENFF_PARAMETERS to its location."
        )
    records = [
        {
            "kind": "parameters",
            "product_id": entry["id"],
            "relative_path": "mvp_cpds/00_par_all36_cgenff.prm",
            "source_path": source,
            "sha256": parent["sha256"],
        }
    ]
    for kind, record in entry["assets"].items():
        source = (ROOT / record["path"]).resolve()
        if (
            not source.is_relative_to(ROOT.resolve())
            or not source.is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]
        ):
            raise CpdCapabilityError(
                f"Provisional CPD asset is missing or hash-mismatched: {record['path']}"
            )
        records.append(
            {
                "kind": kind,
                "product_id": entry["id"],
                "relative_path": record["path"],
                "source_path": source,
                "sha256": record["sha256"],
            }
        )
    return records


def validate_design(design):
    package_assets(design)
    seeds = json.loads(SEEDS.read_text())["products"]
    owners = {x.id: x for x in [*design.crossovers, *design.forced_ligations]}
    from backend.core.base_keys import parse_base_key, resolve_base_keys

    for lesion in design.photoproduct_junctions:
        seed = next(p for p in seeds if p["stereochemistry"] == lesion.stereochemistry)
        if (
            lesion.bond_relaxation.get("seed_sha256") != seed["source_sha256"]
            or len(lesion.context_coordinates) != 4
            or lesion.patch_order != "base-key-1-first"
            or set(lesion.design_coordinates) != {lesion.base_key_1, lesion.base_key_2}
            or any(
                not {"C1'", "N1", "C5", "C6", "H6"}.issubset(atoms)
                for atoms in lesion.design_coordinates.values()
            )
        ):
            raise CpdCapabilityError(
                "Provisional CPD simulation requires a complete reviewed six-residue starting geometry."
            )
        endpoints, errors = resolve_base_keys(
            design, [lesion.base_key_1, lesion.base_key_2], require_atoms=False
        )
        if errors or len(endpoints) != 2 or any(e.base != "T" for e in endpoints):
            raise CpdCapabilityError(
                "Provisional CPD thymine endpoints no longer resolve."
            )
        for key in [lesion.base_key_1, lesion.base_key_2]:
            p = parse_base_key(key)
            if (
                p.family != "xover"
                or p.k != 0
                or p.crossover_id not in owners
                or owners[p.crossover_id].extra_bases != "T"
            ):
                raise CpdCapabilityError(
                    "Provisional six-residue CPDs currently require two single-T crossover inserts."
                )
        definition = load_chemical_definition(lesion.product, lesion.stereochemistry)
        if not audit_product_chirality(definition, world_core(design, lesion))[
            "passed"
        ]:
            raise CpdCapabilityError(
                "Provisional CPD stereochemistry does not match the requested isomer."
            )


def world_core(design, lesion):
    from backend.core.base_keys import parse_base_key
    from backend.core.cpd_conversion import endpoint_transform

    result = {}
    for i, key in enumerate([lesion.base_key_1, lesion.base_key_2], 1):
        pose = endpoint_transform(design, parse_base_key(key))
        for n, p in lesion.design_coordinates[key].items():
            p = np.array(p)
            if pose:
                pivot = np.array(pose.pivot)
                p = (
                    pivot
                    + Rotation.from_quat(pose.rotation).apply(p - pivot)
                    + pose.translation
                )
            result[f"{i}:{n}"] = p.tolist()
    return result


def simulation_registry(design):
    if uses_mvp(design):
        return manifest()
    from backend.core.photoproduct_registry import photoproduct_registry

    return photoproduct_registry()


def fix_and_audit_pdb(design, pdb_text, patch_plan):
    """Supply H6 from the authored chiral core; psfgen IC guessing is not stereospecific."""
    from backend.core.namd_topology import charmm_atom_name

    lines = pdb_text.splitlines()
    positions = {}
    for i, line in enumerate(lines):
        if line.startswith(("ATOM  ", "HETATM")):
            positions[(line[72:76].strip(), int(line[22:26]), line[12:16].strip())] = i
    for lesion in design.photoproduct_junctions:
        core = world_core(design, lesion)
        patch = next(p for p in patch_plan["patches"] if p["lesion_id"] == lesion.id)
        endpoints = {e["endpoint"]: e for e in patch["endpoints"]}
        for number in (1, 2):
            e = endpoints[number]
            i = positions[(e["segid"], e["resid"], "H6")]
            xyz = np.array(core[f"{number}:H6"]) * 10
            lines[i] = lines[i][:30] + "".join(f"{v:8.3f}" for v in xyz) + lines[i][54:]
        actual = {}
        for reference in core:
            number, name = reference.split(":")
            e = endpoints[int(number)]
            i = positions.get((e["segid"], e["resid"], charmm_atom_name(name)))
            if i is not None:
                actual[reference] = [float(lines[i][j : j + 8]) for j in (30, 38, 46)]
        if not audit_product_chirality(
            load_chemical_definition(lesion.product, lesion.stereochemistry), actual
        )["passed"]:
            raise CpdCapabilityError(
                "Prepared NAMD coordinates failed the CPD stereochemistry audit."
            )
    return "\n".join(lines) + "\n"
