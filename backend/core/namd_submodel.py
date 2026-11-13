"""Derived NAMD submodels. Never construct a cropped NADOC Design.

Keep whole residues and the complete bonded support of mobile atoms; cuts occur
only in fixed context. Original atom/residue identities and source receipts remain.
"""

import io
import zipfile
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from backend.physics.oxdna_submodel import box_distance
from backend.core.pdb_export import _h36

_ARITY = {
    "NBOND": 2,
    "NTHETA": 3,
    "NPHI": 4,
    "NIMPHI": 4,
    "NDON": 2,
    "NACC": 2,
    "NCRTERM": 8,
}


def sections(text):
    lines = text.splitlines()
    headers = []
    for i, line in enumerate(lines):
        match = re.match(r"\s*(\d+)(?:\s+\d+)?\s+!(\w+)", line)
        if match:
            headers.append((i, int(match[1]), match[2]))
    result = {}
    for k, (i, n, name) in enumerate(headers):
        end = headers[k + 1][0] if k + 1 < len(headers) else len(lines)
        result[name] = (n, [s for s in lines[i + 1 : end] if s.strip()])
    return result


def crop_topology(topology, box):
    from backend.core.namd_topology import CharmmTopologyBuild

    source = sections(topology.psf_text)
    n, atom_lines = source["NATOM"]
    records = [s.split() for s in atom_lines]
    pdb = [
        s for s in topology.pdb_text.splitlines() if s.startswith(("ATOM  ", "HETATM"))
    ]
    if n != len(records) or n != len(pdb):
        raise ValueError("Submodel PSF/PDB count mismatch")
    residues = [(s[1], s[2]) for s in records]
    positions = np.array(
        [[float(line[i : i + 8]) / 10 for i in (30, 38, 46)] for line in pdb]
    )
    # Whole-residue policy: select a nucleotide when its phosphate lies in the
    # box, using C1' only at a terminal residue lacking phosphate.
    representative = {}
    for i, row in enumerate(records):
        if row[4] == "P" or (residues[i] not in representative and row[4] == "C1'"):
            representative[residues[i]] = i
    if set(residues) != set(representative):
        raise ValueError("NAMD submodels currently require DNA-only residue topology")
    distance = box_distance(positions, box)
    mobile_res = {r for r, i in representative.items() if distance[i] <= 1e-10}
    if not mobile_res:
        raise ValueError("The submodel box selects no DNA phosphate sites")
    mobile = {i + 1 for i, r in enumerate(residues) if r in mobile_res}
    retained_res = {
        r
        for i, r in enumerate(residues)
        if distance[i] <= box.get("shell_nm", 3) + 1e-10
    } | mobile_res
    terms = {}
    for name, (count, lines) in source.items():
        if name in _ARITY:
            flat = list(map(int, " ".join(lines).split()))
            arity = _ARITY[name]
            if len(flat) != count * arity:
                raise ValueError(f"Invalid PSF {name}")
            terms[name] = [
                tuple(flat[i : i + arity]) for i in range(0, len(flat), arity)
            ]
            for term in terms[name]:
                if mobile.intersection(term):
                    retained_res.update(residues[i - 1] for i in term)
        elif name not in ("NTITLE", "NATOM", "NNB", "NGRP") and count:
            raise ValueError(f"Unsupported PSF section {name}")
    if source.get("NNB", (0, []))[0]:
        raise ValueError("Explicit PSF exclusions require submodel remapping")
    kept = [i + 1 for i, r in enumerate(residues) if r in retained_res]
    mapping = {old: new + 1 for new, old in enumerate(kept)}
    out = [
        topology.psf_text.splitlines()[0],
        "",
        "       1 !NTITLE",
        " REMARKS NADOC derived simulation submodel; see submodel.json",
        "",
        f"{len(kept):8d} !NATOM",
    ]
    out += [f"{mapping[i]:8d} " + atom_lines[i - 1].split(maxsplit=1)[1] for i in kept]
    cuts = []
    for name, arity in _ARITY.items():
        if name not in source:
            continue
        retained = []
        for term in terms[name]:
            if all(i in mapping for i in term):
                retained.append(tuple(mapping[i] for i in term))
            else:
                if mobile.intersection(term):
                    raise ValueError("Cannot cut a bonded term touching a mobile atom")
                if name == "NBOND" and any(i in mapping for i in term):
                    cuts.append(list(term))
        out += ["", f"{len(retained):8d} !{name}"]
        flat = [i for term in retained for i in term]
        width = 9 if arity == 3 else 8
        out += [
            "".join(f"{i:8d}" for i in flat[j : j + width])
            for j in range(0, len(flat), width)
        ]
    out += ["", "       0 !NNB"]
    out += ["".join(f"{0:8d}" for _ in kept[j : j + 8]) for j in range(0, len(kept), 8)]
    out += ["", "       1       0 !NGRP", "       0       0       0", ""]
    recipe = dict(
        version=2,
        box=box,
        source_atoms=n,
        source_residues=[list(r) for r in dict.fromkeys(residues)],
        retained_source_indices=[i - 1 for i in kept],
        mobile_source_indices=sorted(i - 1 for i in mobile),
        mobile_output_indices=[mapping[i] - 1 for i in sorted(mobile)],
        mobile_residues=[list(r) for r in sorted(mobile_res)],
        retained_residues=[list(r) for r in sorted(retained_res)],
        cut_bonds_source_indices=[[a - 1, b - 1] for a, b in cuts],
        source_psf_sha256=hashlib.sha256(topology.psf_text.encode()).hexdigest(),
        source_pdb_sha256=hashlib.sha256(topology.pdb_text.encode()).hexdigest(),
        boundary_policy="Whole residues; retain every bonded term touching mobile atoms; cut only fixed-context terms; no artificial caps or charge edits",
    )
    from backend.core.namd_submodel_boundary import boundary_recipe

    recipe["shell_boundary"] = boundary_recipe(
        source, residues, representative, distance, kept, mobile, terms, box
    )
    pdb_text = (
        "\n".join(pdb[i - 1][:6] + _h36(mapping[i], 5) + pdb[i - 1][11:] for i in kept)
        + "\nEND\n"
    )
    metadata = {**topology.metadata, "submodel": recipe}
    metadata.pop("json", None)
    metadata["source_audit"] = metadata.pop("audit", None)
    return CharmmTopologyBuild(
        pdb_text=pdb_text, psf_text="\n".join(out), metadata=metadata
    ), recipe


def selection_summary(receipt):
    """Small, JSON-safe census shared by relaxation and production forecasts."""
    retained = len(receipt['retained_source_indices'])
    mobile = len(receipt['mobile_source_indices'])
    return dict(source_solute_atoms=receipt['source_atoms'], retained_solute_atoms=retained,
                mobile_solute_atoms=mobile, shell_solute_atoms=retained-mobile,
                shell_nm=float(receipt['box'].get('shell_nm', 3)))


def package_builder(box, *, reference_profile=None):
    def build(design, **kwargs):
        from backend.core.namd_topology import build_charmm_psfgen_topology
        from backend.core.namd_solvate import build_namd_solvated_package

        if (
            kwargs.get("graphene_nanopore")
            or kwargs.get("solute_coords") is not None
            or kwargs.get("graphene_only")
        ):
            raise ValueError(
                "NAMD submodels currently support DNA-only direct preparation"
            )
        full = build_charmm_psfgen_topology(
            design, atomistic_model=kwargs.get("atomistic_model")
        )
        cropped, recipe = crop_topology(full, box)
        from backend.core.namd_submodel_charge import record_charge_policy

        recipe["charge_policy"] = record_charge_policy(full.psf_text, cropped.psf_text)
        if reference_profile:
            from backend.core.namd_submodel_reference import topology_signature
            signature = topology_signature(json.loads(design.to_json()))
            # Physics settings can be shared with screening variants. Coordinate
            # transfer has stricter identity requirements and is NOT performed here.
            recipe["reference_topology_match"] = signature == reference_profile["topology_sha256"]
            recipe["source_topology_sha256"] = signature
            recipe["reference_profile"] = reference_profile
            kwargs.update(counterion=reference_profile["counterion"], ion_conc_mM=reference_profile["nacl_mM"], mg_conc_mM=reference_profile["mgcl2_mM"])
        data = build_namd_solvated_package(design, topology_override=cropped, **kwargs)
        buffer = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(data)) as source,
            zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive,
        ):
            for name in source.namelist():
                content = source.read(name)
                if name.endswith(".psf"):
                    content = canonical_bonded_lines(content.decode()).encode()
                archive.writestr(name, content)
            prefix = next(
                n.rsplit("/", 1)[0]
                for n in archive.namelist()
                if n.endswith("/namd.conf")
            )
            archive.writestr(prefix + "/submodel.json", json.dumps(recipe, indent=2))
            archive.writestr(prefix + "/submodel_source/full.psf", full.psf_text)
            archive.writestr(prefix + "/submodel_source/full.pdb", full.pdb_text)
        return buffer.getvalue()

    return build


def finalize_package(package_dir, name_stem):
    """Apply the recorded boundary recipe, preserving legacy fixed-shell jobs."""
    package_dir = Path(package_dir)
    receipt = package_dir / "submodel.json"
    if not receipt.exists():
        return
    recipe = json.loads(receipt.read_text())
    pdb = (package_dir / f"{name_stem}.pdb").read_text().splitlines()
    atoms = [s for s in pdb if s.startswith(("ATOM  ", "HETATM"))]
    retained = len(recipe["retained_source_indices"])
    mobile = set(recipe["mobile_output_indices"])
    boundary = recipe.get("shell_boundary")
    fixed = (
        set(boundary["fixed_output_indices"])
        if boundary
        else {i for i in range(retained) if i not in mobile}
    )
    if len(atoms) < retained:
        raise ValueError("Submodel marker exceeds solvated topology")
    written_markers = set()
    for conf in package_dir.glob("*.conf"):
        text = conf.read_text()
        if recipe.get("reference_profile"):
            from backend.core.namd_submodel_reference import apply_package_profile
            text = apply_package_profile(package_dir, text, recipe["reference_profile"])
        prior = re.search(r"^\s*fixedAtomsFile\s+(\S+)", text, re.M | re.I)
        union = set(fixed)
        if prior:
            old = package_dir / prior[1]
            old_atoms = [
                s
                for s in old.read_text().splitlines()
                if s.startswith(("ATOM  ", "HETATM"))
            ]
            if len(old_atoms) != len(atoms):
                raise ValueError(
                    "Existing fixed atom marker count differs from submodel"
                )
            union.update(i for i, s in enumerate(old_atoms) if float(s[60:66]) != 0)
        marker = (
            "submodel_fixed.pdb"
            if union == fixed
            else f"submodel_fixed_{conf.stem}.pdb"
        )
        if marker not in written_markers:
            marked = [
                s[:60] + f"{1.0 if i in union else 0.0:6.2f}" + s[66:]
                for i, s in enumerate(atoms)
            ]
            (package_dir / marker).write_text("\n".join(marked) + "\nEND\n")
            written_markers.add(marker)
        text = re.sub(
            r"^[ \t]*(?:fixedAtoms(?:File|Col|Forces)?|GPUresident|langevinPiston)\s+[^\n]*\n?",
            "",
            text,
            flags=re.M | re.I,
        )
        block = f"fixedAtoms on\nfixedAtomsFile {marker}\nfixedAtomsCol B\nfixedAtomsForces off\nlangevinPiston off\n"
        # Before Tcl loops: fixedAtoms cannot be reconfigured after startup.
        if boundary:
            from backend.core.namd_submodel_boundary import apply_restraints

            text = apply_restraints(package_dir, conf, text, atoms, boundary)
        text = block + text
        conf.write_text(text)
    manifest_path = package_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        source_pdb = package_dir / "submodel_source" / "full.pdb"
        if (
            "source_cell_center_nm" not in recipe
            and source_pdb.exists()
            and manifest.get("box_ang")
        ):
            source_atoms = [
                line
                for line in source_pdb.read_text().splitlines()
                if line.startswith(("ATOM  ", "HETATM"))
            ]
            original = source_atoms[recipe["retained_source_indices"][0]]
            shift = [
                (float(atoms[0][i : i + 8]) - float(original[i : i + 8])) / 10
                for i in (30, 38, 46)
            ]
            recipe["source_to_package_translation_nm"] = shift
            recipe["source_cell_center_nm"] = [
                float(length) / 20 - delta
                for length, delta in zip(manifest["box_ang"], shift)
            ]
            receipt.write_text(json.dumps(recipe, indent=2))
        manifest["submodel"] = recipe
        if recipe.get("reference_profile"):
            profile = recipe["reference_profile"]
            manifest["submodel_reference"] = profile
            for stage in manifest.get("segments", []):
                stage.update(damping=float(profile["physics"]["langevinDamping"]), temp=float(profile["physics"]["langevinTemp"]), timestep_fs=float(profile["physics"]["timestep"]))
            if manifest.get("production_recipe"):
                manifest["production_recipe"]["langevin_damping"] = float(profile["physics"]["langevinDamping"])
        if recipe.get("charge_policy") and "equilibrium_aware" in manifest:
            manifest["equilibrium_aware"].update(
                requires_neutral_final_psf=False,
                expected_final_charge_e=recipe["charge_policy"]["residual_charge_e"],
            )
        manifest.setdefault("solvation", {})["npt_allowed"] = False
        manifest["gpu_resident_mode"] = "off"
        for key in ("fast_relaxation", "fast_production"):
            if isinstance(manifest.get(key), dict):
                manifest[key]["gpu_resident"] = False
        manifest["submodel_execution"] = dict(
            fixed_atoms=len(fixed),
            mobile_solute_atoms=retained - len(fixed),
            core_atoms=len(mobile),
            restrained_shell_atoms=len(boundary["restrained_output_indices"])
            if boundary
            else 0,
            total_atoms=len(atoms),
            ensemble="NVT",
            gpu_resident=False,
            receipt="submodel.json",
        )
        for name in ("manifest.json", "nadoc_md_run.json"):
            (package_dir / name).write_text(json.dumps(manifest, indent=2))


def canonical_bonded_lines(text):
    """Pack complete PSF terms per line, including the DNA/solvent join.

    NAMD accepts arbitrary whitespace; MDAnalysis requires 4 bonds, 3 angles or
    2 dihedrals per line. Do not preserve partial lines at the solvent boundary.
    """
    pattern = r"(^[^\n]*!(NBOND|NTHETA|NPHI|NIMPHI|NDON|NACC|NCRTERM)[^\n]*\n)([\s\d]*)(?=^.*!|\Z)"

    def reflow(match):
        values = list(map(int, match[3].split()))
        count = int(match[1].split()[0])
        arity = _ARITY[match[2]]
        if len(values) != count * arity:
            raise ValueError(f"Invalid PSF section {match[2]}")
        width = 9 if arity == 3 else 8
        return (
            match[1]
            + "\n".join(
                "".join(f"{i:8d}" for i in values[j : j + width])
                for j in range(0, len(values), width)
            )
            + "\n\n"
        )

    return re.sub(pattern, reflow, text, flags=re.M)


def fixed_shell_memory(package_dir, options, estimate):
    """Conservative fixed-mask allowance; all simulated atoms keep the full budget.

    Qualified native path: literal B-column flags, fixed forces off, NVT and
    CPU/GPU offload. Budget mapping/flag/coordinate buffers without subtracting
    fixed atoms from the ordinary topology, solvent or neighbor allocations.
    """
    from dataclasses import replace
    import math

    if estimate.gpu_resident:
        raise ValueError("NAMD fixed atoms require CPU or GPU offload")
    if options.get("langevinpiston", "off").lower() not in ("off", "no", "false", "0"):
        raise ValueError(
            "NAMD submodel memory qualification requires a fixed-volume cell"
        )
    if options.get("fixedatomscol", "").upper() != "B" or options.get(
        "fixedatomsforces", "off"
    ).lower() not in ("off", "no", "false", "0"):
        raise ValueError("Unqualified fixed-atom settings")
    marker = Path(package_dir) / options.get("fixedatomsfile", "")
    flags = [
        float(line[60:66])
        for line in marker.read_text().splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    if len(flags) != estimate.atoms or any(value not in (0, 1) for value in flags):
        raise ValueError(
            "Fixed atom marker must have one binary flag per simulated atom"
        )
    host = math.ceil(64 * estimate.atoms / 1024**2)
    gpu = math.ceil(32 * estimate.atoms / 1024**2)
    components = {**(estimate.components or {})}
    components["host"] = {**components.get("host", {}), "fixed_atom_buffers_mib": host}
    components["gpu"] = {**components.get("gpu", {}), "fixed_atom_buffers_mib": gpu}
    return replace(
        estimate,
        ram_mib=estimate.ram_mib + host,
        gpu_mib=estimate.gpu_mib + gpu,
        components=components,
    )
