"""Shared, isolated NAMD qualification packages for neutral atomistic gold.

No abstract walls, biomolecular placement, cloud launch or production qualification.
All preparation inputs persist in the manifest; output directories are never reused.
"""

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

import numpy as np
from scipy.spatial import cKDTree

from backend.core import gold_geometry, gold_model
from backend.core.md_charge import parse_psf_atoms, audit_psf
from backend.core import namd_solvate as solvate
from backend.core.namd_slab import COULOMB

FF_FILES = ("par_all36_na.prm", "par_all36m_prot.prm",
            "toppar_water_ions_cufix.str", "par_stub_ions_nbfix.str")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def layout(spec):
    """A slit bounded by two physical slabs, or a fully solvated isolated particle."""
    if not isinstance(spec, dict):
        raise ValueError("Gold geometry must be an explicit descriptor")
    allowed = {"kind", "facet", "repeats", "layers", "gap_nm", "vacuum_factor",
               "radius_nm", "solvent_padding_nm", "lattice_nm"}
    if set(spec) - allowed:
        raise ValueError(f"Unknown gold geometry fields: {sorted(set(spec)-allowed)}")
    a = spec.get("lattice_nm", gold_model.MODEL["lattice_parameter_nm"])
    if spec.get("kind") == "slab":
        if set(spec) & {"radius_nm", "solvent_padding_nm"}:
            raise ValueError("Nanoparticle dimensions cannot be supplied for a slab")
        xyz, geom = gold_geometry.slab(spec.get("facet", "111"), spec.get("repeats", [16, 9]),
                                       spec.get("layers", 5), a)
        gap, vacuum = spec.get("gap_nm", 4.), spec.get("vacuum_factor", 3.)
        if not math.isfinite(gap) or not 2.5 <= gap <= 30:
            raise ValueError("Gold slit gap must be 2.5..30 nm")
        if not math.isfinite(vacuum) or not 3 <= vacuum <= 6:
            raise ValueError("Slab vacuum factor must be 3..6")
        thickness = geom["thickness_nm"]
        height = 2*thickness+gap
        shift = (vacuum-1)*height/2
        other = xyz.copy()
        other[:, 2] += thickness+gap
        xyz = np.concatenate((xyz, other))
        xyz[:, 2] += shift
        cell = [*geom["lateral_nm"], height*vacuum]
        geom.update(liquid_bounds_nm=[shift+thickness, shift+thickness+gap],
                    slabs=2, sites_per_slab=len(xyz)//2, vacuum_factor=vacuum)
    elif spec.get("kind") == "nanoparticle":
        if set(spec) & {"facet", "repeats", "layers", "gap_nm", "vacuum_factor"}:
            raise ValueError("Slab geometry/correction cannot be supplied for a nanoparticle")
        xyz, geom = gold_geometry.nanoparticle(spec.get("radius_nm", 1.), a)
        padding = spec.get("solvent_padding_nm", 1.6)
        if not math.isfinite(padding) or not 1.3 <= padding <= 10:
            raise ValueError("Nanoparticle solvent padding must be 1.3..10 nm")
        cell = [2*(geom["radius_nm"]+padding)]*3
        xyz += np.array(cell)/2
        geom.update(center_nm=(np.array(cell)/2).tolist(), solvent_padding_nm=padding)
    else:
        raise ValueError("Gold geometry kind must be slab or nanoparticle")
    if min(cell) < 4.0 or np.prod(cell) > 100000:
        raise ValueError("Gold resident qualification requires dimensions >=4 nm and volume <=100,000 nm³; smaller slab cells showed GPU exclusion failures")
    return xyz, cell, geom


def pack(waters, xyz, cell, geom, salt_mM, seed, ceiling):
    """Carve whole waters by atom-specific Au LJ contact; replace eligible waters with ions."""
    tree = cKDTree(np.mod(xyz, cell), boxsize=cell)
    points = np.array([list(asdict(w).values()) for w in waters]).reshape(-1, 3, 3)
    allowed = np.ones(len(points), dtype=bool)
    if geom["kind"] == "slab":
        low, high = geom["liquid_bounds_nm"]
        allowed &= np.all((points[:, :, 2] > low) & (points[:, :, 2] < high), axis=1)
    for atom, partner in enumerate(("OT", "HT", "HT")):
        distance = tree.query(np.mod(points[:, atom], cell))[0]
        allowed &= distance >= gold_model.contact_distance_nm(partner, ceiling)
    retained = [w for w, keep in zip(waters, allowed) if keep]
    oxygen = points[allowed, 0]
    if len(retained) < 100:
        raise ValueError("Gold geometry leaves fewer than 100 waters")
    # Use retained water inventory, not vacuum or metal volume, to set initial salt.
    # This nominal ratio is reported explicitly; bulk concentration is an observable.
    count = int(math.floor(len(retained)*salt_mM/(55.5*1000)+.5))
    rng = np.random.default_rng(seed)
    chosen = set()
    ions = []
    for partner in ("SOD", "CLA"):
        if count == 0:
            ions.append([])
            continue
        eligible = np.flatnonzero(tree.query(np.mod(oxygen, cell))[0] >=
                                 gold_model.contact_distance_nm(partner, ceiling))
        selected = []
        for i in rng.permutation(eligible):
            if int(i) in chosen:
                continue
            selected.append(tuple(oxygen[i]))
            chosen.add(int(i))
            if len(selected) == count:
                break
        if len(selected) != count:
            raise ValueError("Insufficient nonoverlapping gold-ion sites")
        ions.append(selected)
    remaining = [w for i, w in enumerate(retained) if i not in chosen]
    return remaining, *ions, {"candidate_waters": len(waters), "retained_before_ions": len(retained),
        "packing_energy_ceiling_kcal_mol": ceiling, "n_water": len(remaining),
        "n_na": count, "n_cl": count, "salt_loading": "pairs / retained pre-ion waters * 55.5 M",
        "nominal_salt_mM": salt_mM,
        "realized_water_ratio_mM": count/len(remaining)*55500,
        "minimum_distances_nm": {p: gold_model.contact_distance_nm(p, ceiling)
                                 for p in ("OT", "HT", "SOD", "CLA")}}


def dry_pair(xyz):
    atoms, records = [], []
    for i, p in enumerate(xyz):
        seg, resid = f"A{i//9999:03d}", i % 9999+1
        atoms.append(solvate._psf_atom_line(i+1, seg, resid, "AUI", "AU", "NAUI", 0., 196.96657))
        records.append(solvate._hetatm_record(i+1, "AU", "AUI", "A", resid,
                                              *(p*10), segname=seg).ljust(76)+"AU")
    psf = "PSF EXT\n\n       1 !NTITLE\n REMARKS neutral INTERFACE gold\n\n"
    psf += f"{len(atoms):8d} !NATOM\n"+"\n".join(atoms)+"\n\n"
    for header in ("NBOND: bonds", "NTHETA: angles", "NPHI: dihedrals", "NIMPHI: impropers",
                   "NDON: donors", "NACC: acceptors", "NNB"):
        psf += f"       0 !{header}\n\n"
    psf += "       0       0 !NGRP NST2\n\n"
    return psf, "\n".join(records)+"\nEND\n"


def build_package(destination, geometry, *, model_id=gold_model.MODEL_ID, mobility="restrained",
                  restraint_k=10., salt_mM=150., temperature_K=298.15, seed=17,
                  packing_ceiling=6., water_loading_scale=1., gpu_registry=None):
    """Build an inspectable package. No job launch; caller must supply a new path."""
    model = gold_model.specification(model_id)
    if mobility not in model["mobility"]:
        raise ValueError("Gold mobility must be fixed, restrained or mobile")
    if not math.isfinite(restraint_k) or not 0 < restraint_k <= 100:
        raise ValueError("Native restraint coefficient must be in (0,100] kcal/mol/Å²")
    if round(restraint_k, 2) != restraint_k:
        raise ValueError("Native PDB restraint coefficients require at most two decimal places")
    if not math.isfinite(water_loading_scale) or not .9 <= water_loading_scale <= 1.3:
        raise ValueError("Explicit water template loading scale must be 0.9..1.3")
    if not math.isfinite(salt_mM) or not 0 <= salt_mM <= 1000:
        raise ValueError("Gold baseline salt must be 0..1000 mM NaCl")
    if not math.isfinite(temperature_K) or not 270 <= temperature_K <= 330:
        raise ValueError("Gold baseline temperature must be 270..330 K")
    if type(seed) is not int or not 1 <= seed < 2147483647:
        raise ValueError("Seed must be an integer in 1..2147483646")
    gold_model.contact_distance_nm("OT", packing_ceiling)
    dest = Path(destination)
    if dest.exists():
        raise FileExistsError(dest)
    gold_model.validate_electrolyte((solvate._FF_DIR/"toppar_water_ions_cufix.str").read_text())
    xyz, cell, geom = layout(geometry)
    psf, pdb = dry_pair(xyz)
    # Build a bulk water template without GROMACS's guessed Au radii or recentering.
    with tempfile.TemporaryDirectory(prefix="nadoc_gold_water_") as tmp:
        linear_scale = water_loading_scale**(1/3)
        command = [solvate._find_gmx(), "solvate", "-cs", "spc216.gro", "-box",
                   *(f"{v*linear_scale:.8f}" for v in cell), "-o", "water.gro", "-nobackup"]
        run = subprocess.run(command, cwd=tmp, capture_output=True, text=True, timeout=90)
        if run.returncode:
            raise RuntimeError("Bulk water packing failed: "+run.stderr[-2000:])
        waters, _ = solvate._parse_gro((Path(tmp)/"water.gro").read_text())
    # Change oxygen centers, not intramolecular water geometry. This is explicit
    # solvent inventory calibration, not a change to any gold/water force parameter.
    if water_loading_scale != 1.:
        translated = []
        for w in waters:
            p = np.array(list(asdict(w).values())).reshape(3, 3)
            p += p[0]/linear_scale-p[0]
            translated.append(solvate._Water(*p.ravel()))
        waters = translated
    waters, na, cl, packing = pack(waters, xyz, cell, geom, salt_mM, seed, packing_ceiling)
    packing["water_loading_scale"] = water_loading_scale
    psf = solvate._extend_psf(psf, waters, na, cl)
    pdb = solvate._build_solvated_pdb(pdb, waters, na, cl, tuple(cell), len(xyz))
    audit = audit_psf(psf, require_neutral=True, require_dna_hydrogens=False,
                      require_dna_residue_charge=False)
    if not audit.passed:
        raise ValueError("Gold PSF failed charge audit: "+"; ".join(audit.errors))
    atoms = parse_psf_atoms(psf)
    if {a.atomtype for a in atoms} - set(gold_model.PARTNERS):
        raise ValueError("Unsupported atom types in bare-gold package")
    expected_charge = {"NAUI": 0., "OT": -.834, "HT": .417, "SOD": 1., "CLA": -1.}
    if any(a.charge != expected_charge[a.atomtype] or not math.isfinite(a.mass) or a.mass <= 0 for a in atoms):
        raise ValueError("Bare-gold PSF charge/mass differs from the reviewed model")
    dest.mkdir(parents=True)
    (dest/"forcefield").mkdir()
    (dest/"output").mkdir()
    for name in FF_FILES:
        shutil.copy2(solvate._FF_DIR/name, dest/"forcefield"/name)
    (dest/"forcefield/gold.prm").write_text(gold_model.parameter_text())
    (dest/"system.psf").write_text(psf)
    (dest/"system.pdb").write_text(pdb)
    # Native constraints use U=k*|r-r0|². Fixed atoms use the same selection map.
    rows, ordinal = [], 0
    for row in pdb.splitlines():
        if row.startswith(("ATOM  ", "HETATM")):
            ordinal += 1
            value = (restraint_k if mobility == "restrained" else 1.) if ordinal <= len(xyz) else 0.
            row = row[:60]+f"{value:6.2f}"+row[66:]
        rows.append(row)
    (dest/"gold_reference.pdb").write_text("\n".join(rows)+"\n")
    manifest = {"schema": "nadoc.gold_package.v1", "gold_model": model, "geometry_input": geometry,
        "geometry": geom, "cell_nm": cell, "mobility": mobility, "restraint_k_kcal_mol_A2": restraint_k,
        "restraint_convention": "native NAMD U=k*displacement²", "packing": packing,
        "temperature_K": temperature_K, "seed": seed, "n_gold": len(xyz), "n_atoms": len(atoms),
        "electrostatics": "PME+EW3DC" if geom["kind"] == "slab" else "3D PME",
        "hard_wall": False, "qualified": False,
        "validation": {"charge_audit": audit.to_dict(), "physical": "not evaluated"}}
    if geom["kind"] == "slab":
        from backend.core.namd_electrode_gpu import REGISTRY, parameter_text
        registry = Path(gpu_registry or REGISTRY)
        provenance = json.loads((registry/"provenance.json").read_text())
        if sha(registry/"electrode.so") != provenance["plugin_sha256"]:
            raise ValueError("GPU slab library checksum mismatch")
        params = np.zeros((len(atoms), 6))
        params[:, 0] = [a.charge for a in atoms]
        coefficient = 2*math.pi*COULOMB/math.prod(v*10 for v in cell)
        (dest/"electrode_gpu.params").write_text(parameter_text(params, [2, coefficient, 0, cell[2]*10, 0]))
        shutil.copy2(registry/"electrode.so", dest/"electrode_gpu.so")
        manifest["slab_gpu"] = {"engine_sha256": provenance["installed_engine_sha256"],
                                "plugin_sha256": provenance["plugin_sha256"],
                                "wall_force": 0, "anchor_force": 0}
    (dest/"gold_model.json").write_text(json.dumps(model, indent=2)+"\n")
    manifest["asset_sha256"] = {str(p.relative_to(dest)): sha(p) for p in dest.rglob("*") if p.is_file()}
    (dest/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


def verify_package(package, binary=None):
    package = Path(package)
    m = json.loads((package/"manifest.json").read_text())
    if m["gold_model"] != gold_model.specification(m["gold_model"]["id"]):
        raise ValueError("Gold model specification was modified")
    for name, digest in m["asset_sha256"].items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Gold assets must have package-relative paths")
        if sha(package/name) != digest:
            raise ValueError(f"Gold asset changed: {name}")
    if m["geometry"]["kind"] == "nanoparticle" and "slab_gpu" in m:
        raise ValueError("Slab correction is unsupported for nanoparticles")
    if binary and "slab_gpu" in m and sha(binary) != m["slab_gpu"]["engine_sha256"]:
        raise ValueError("Gold slab requires the pinned GPU correction engine")
    if binary and m.get("runtime_engine_sha256") and sha(binary) != m["runtime_engine_sha256"]:
        raise ValueError("Gold continuation engine differs from original execution")
    return m


def config(manifest, *, steps=1000, minimize=0, timestep_fs=1., prefix="probe", restart=None,
           first_step=0, thermostat=True):
    """Native resident NAMD configuration; restart retains binary state and atom map."""
    if timestep_fs not in (.5, 1., 2.) or any(type(v) is not int or v < 0 for v in (steps, minimize, first_step)):
        raise ValueError("Qualification uses 0.5/1/2 fs and nonnegative integer step counts")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", prefix):
        raise ValueError("Invalid gold output prefix")
    if restart is not None and not re.fullmatch(r"[A-Za-z0-9_-]+", restart):
        raise ValueError("Restart must identify a package-local output prefix")
    if restart and minimize:
        raise ValueError("Do not minimize a checkpoint continuation")
    m = manifest
    if m["geometry"]["kind"] == "nanoparticle" and "slab_gpu" in m:
        raise ValueError("Slab correction is unsupported for nanoparticles")
    if m["geometry"]["kind"] == "slab" and "slab_gpu" not in m:
        raise ValueError("Planar gold requires its GPU EW3DC correction")
    cell = [v*10 for v in m["cell_nm"]]
    lines = ["structure system.psf", "coordinates system.pdb", "paraTypeCharmm on"]
    lines += [f"parameters forcefield/{f}" for f in (*FF_FILES, "gold.prm")]
    lines += [f"cellBasisVector1 {cell[0]} 0 0", f"cellBasisVector2 0 {cell[1]} 0",
              f"cellBasisVector3 0 0 {cell[2]}", "cellOrigin "+" ".join(str(v/2) for v in cell),
              "PME on", "PMEGridSpacing 1.0", "PMETolerance 1e-6", "exclude scaled1-4",
              "1-4scaling 1.0", "switching on", "switchdist 10", "cutoff 12", "pairlistdist 14",
              "rigidBonds water", "useSettle on", "wrapAll off", "wrapWater off",
              "nonbondedFreq 1", "fullElectFrequency 1", "stepsPerCycle 10", f"timestep {timestep_fs}",
              "GPUresident on", "GPUAtomMigration off",
              "langevinPiston off", f"langevin {'on' if thermostat else 'off'}",
              f"langevinTemp {m['temperature_K']}", "langevinDamping 1", "langevinHydrogen on",
              f"seed {m['seed']}", f"outputName output/{prefix}", "binaryoutput yes",
              f"restartname output/{prefix}.restart", "restartfreq 1000", "binaryrestart yes",
              f"DCDfile output/{prefix}.dcd", "DCDfreq 100", "outputEnergies 100", "outputTiming 1000"]
    if m["mobility"] == "fixed":
        lines += ["fixedAtoms on", "fixedAtomsFile gold_reference.pdb", "fixedAtomsCol B"]
    elif m["mobility"] == "restrained":
        lines += ["constraints on", "consref gold_reference.pdb", "conskfile gold_reference.pdb",
                  "conskcol B", "constraintScaling 1.0"]
    if restart:
        # NAMD defaults to removing COM velocity even from binary checkpoints.
        # Preserve the saved motion: restraints/thermostats can impart momentum.
        # NAMD 3.0 User's Guide, Dynamics (COMmotion).
        lines += [f"bincoordinates output/{restart}.coor", f"binvelocities output/{restart}.vel",
                  f"extendedSystem output/{restart}.xsc", f"firsttimestep {first_step}",
                  "COMmotion yes"]
    else:
        lines += [f"temperature {m['temperature_K']}"]
    if "slab_gpu" in m:
        lines += ["twoAwayZ on", "gpuGlobal on",
                  "gpuGlobalCreateClient {./electrode_gpu.so} electrode {electrode_gpu.params}"]
    if minimize:
        lines += [f"minimize {minimize}"]
    lines += [f"run {steps}"]
    return "\n".join(lines)+"\n"


def export_package(package, archive):
    """Portable relative-path package with its input hashes; no remote launch."""
    package = Path(package)
    verify_package(package)
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(package.rglob("*")):
            if path.is_file() and "output" not in path.relative_to(package).parts:
                z.write(path, path.relative_to(package))
