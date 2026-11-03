"""Bounded experimental NAMD minimization of isolated 1xT candidates.

Uses provisional MVP force fields; vacuum, fixed surroundings, no dynamics.
Not a simulation-readiness certification or a production export path.
"""

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import atom_base_key
from backend.core.cpd_conversion import CORE_PATH
from backend.core.cpd_product import _proper_kabsch
from backend.core.models import Design
from backend.core.namd_topology import (
    _write_segment_pdbs,
    _psfgen_script,
    charmm_atom_name,
)
from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.photoproduct_psf_audit import parse_psf_atoms, parse_psf_index_section
from backend.parameterization.photoproduct_candidate_context import (
    _run_psfgen,
    _pdb_coordinates,
    _pdb_with_coordinates,
    _namd_binary_coordinates,
)
from backend.parameterization.photoproduct_candidate_engine import (
    _namd_config,
    _run_engine,
    _energy_audit,
)
from scripts.investigate_cpd_1xt_starts import write

PACKAGES = Path(
    ".development-artifacts/cpd-cis-anti-i-bounded-sensitivity-v1/minimum-viable-candidates-v4"
).resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--neighbor-backbones", action="store_true")
    parser.add_argument("--tag", default="namd")
    args = parser.parse_args()
    root = args.root.resolve()
    provenance = json.loads((root / "provenance.json").read_text())
    snapshot = root / "input_snapshot.json"
    assert (
        hashlib.sha256(snapshot.read_bytes()).hexdigest() == provenance["input_sha256"]
    )
    design = Design.from_json(snapshot.read_text())
    keys = provenance["keys"]
    original = build_atomistic_model(design)
    for core in json.loads(CORE_PATH.read_text())["products"]:
        folder = root / core["id"]
        out = folder / args.tag
        out.mkdir(exist_ok=False)
        coords = json.loads((folder / "coordinates.json").read_text())
        model = copy.deepcopy(original)
        for a in model.atoms:
            key = atom_base_key(a)
            if key in keys:
                a.x, a.y, a.z = coords[f"{keys.index(key) + 1}:{a.name}"]
        segments, _ = _write_segment_pdbs(design, out, model)
        ends = []
        for key in keys:
            a = next(a for a in model.atoms if atom_base_key(a) == key)
            seg = next(s for s in segments if s["chain_id"] == a.chain_id)
            ends.append({"segid": seg["segid"], "resid": a.seq_num})
        package = PACKAGES / core["id"]
        manifest = json.loads((package / "manifest.json").read_text())
        # Verify every admitted parameter asset before constructing this new context.
        for entry in manifest["files"]:
            assert (
                hashlib.sha256((package / entry["file"]).read_bytes()).hexdigest()
                == entry["sha256"]
            )
        for parent, digest in manifest["required_parent_sha256"].items():
            assert hashlib.sha256(Path(parent).read_bytes()).hexdigest() == digest
        prefix = out / "context"
        tcl = _psfgen_script(
            segments,
            prefix,
            extra_topologies=[package / "patch.rtf"],
            photoproduct_patches=[{"patch_name": "XCPD", "endpoints": ends}],
        )
        (out / "build.tcl").write_text(tcl)
        _run_psfgen(Path(shutil.which("psfgen")), tcl, out, out / "psfgen.log")
        psf = prefix.with_suffix(".psf")
        pdb = prefix.with_suffix(".pdb")
        text = psf.read_text()
        atoms = parse_psf_atoms(text)
        xyz = _pdb_coordinates(pdb)
        identities = {(a.segid, a.resid, a.name): i for i, a in enumerate(atoms)}

        def resolve(addr):
            e, n = addr.split(":")
            end = ends[int(e) - 1]
            return identities[(end["segid"], str(end["resid"]), charmm_atom_name(n))]

        # psfgen guesses new H6 without stereochemical knowledge. Transfer it from
        # the exact rigid core used by the repair, never infer its side from ICs.
        names = [
            f"{i}:{n}" for i in (1, 2) for n in ["N1", "C2", "N3", "C4", "C5", "C6"]
        ]
        r, t, _ = _proper_kabsch(
            np.array([core["coordinates"][k] for k in names]),
            np.array([coords[k] for k in names]),
        )
        for i in (1, 2):
            xyz[resolve(f"{i}:H6")] = (
                r @ np.array(core["coordinates"][f"{i}:H6"]) + t
            ) * 10
        pdb.write_text(_pdb_with_coordinates(pdb, xyz))
        mobile = np.array(
            [
                any(a.segid == e["segid"] and a.resid == str(e["resid"]) for e in ends)
                for a in atoms
            ]
        )
        if args.neighbor_backbones:
            sugar_phosphate = {"P", "O1P", "O2P", "H5T", "H3T"}
            for j, a in enumerate(atoms):
                if any(
                    a.segid == e["segid"] and abs(int(a.resid) - e["resid"]) == 1
                    for e in ends
                ):
                    if "'" in a.name or a.name in sugar_phosphate:
                        mobile[j] = True
        lines = pdb.read_text().splitlines()
        index = 0
        fixed = []
        for line in lines:
            if line.startswith(("ATOM  ", "HETATM")):
                line = f"{line[:60]}{float(not mobile[index]):6.2f}{line[66:]}"
                index += 1
            fixed.append(line)
        (out / "fixed.pdb").write_text("\n".join(fixed) + "\n")
        definition = load_chemical_definition("TT-CPD", core["stereochemistry"])
        refs = {
            v
            for c in definition["product_stereocenters"]
            for v in [c["atom"], *c["signed_volume_reference_atoms"]]
        }

        def chirality(points):
            return audit_product_chirality(
                definition, {k: points[resolve(k)].tolist() for k in refs}
            )

        assert chirality(xyz)["passed"]
        # Verify that both intended crosslinks are actually present in the PSF.
        bonds = parse_psf_index_section(text, "!NBOND", 2)
        bondset = {tuple(sorted((a - 1, b - 1))) for a, b in bonds}
        for b in definition["graph_delta"]["bonds_added"]:
            assert (
                tuple(sorted((resolve(b["atom_1"]), resolve(b["atom_2"])))) in bondset
            )
        config = _namd_config(
            topology_psf=psf,
            starting_coordinates=pdb,
            nucleic_parameters=Path(
                "backend/data/forcefield/par_all36_na.prm"
            ).resolve(),
            lesion_parameters=package / "overlay.prm",
            output_stem=out / "minimized",
            action="minimize",
            steps=args.steps,
        )
        cgenff = next(
            p
            for p in manifest["required_parents"]
            if p.endswith("par_all36_cgenff.prm")
        )
        config = config.replace(
            f"parameters {package}", f"parameters {cgenff}\nparameters {package}", 1
        )
        config = config.replace(
            f"minimize {args.steps}",
            f"fixedAtoms on\nfixedAtomsFile {out}/fixed.pdb\nfixedAtomsCol B\nminimize {args.steps}",
        )
        conf = out / "minimize.namd"
        conf.write_text(config)
        engine = _run_engine(
            [shutil.which("namd3"), "+p1", str(conf)],
            cwd=out,
            stdin=None,
            log_path=out / "minimize.log",
        )
        write(out / "engine.json", engine)
        if not (out / "minimized.coor").exists():
            print(core["id"], "ENGINE FAILED", flush=True)
            continue
        final = _namd_binary_coordinates(out / "minimized.coor", len(atoms))
        (out / "minimized.pdb").write_text(_pdb_with_coordinates(pdb, final))

        def lengths(points, kind):
            pairs = (
                [
                    (a - 1, b - 1)
                    for a, b in bonds
                    if (mobile[a - 1] != mobile[b - 1])
                    if kind == "boundary"
                ]
                if kind == "boundary"
                else [(resolve(f"{i}:N1"), resolve(f"{i}:C1'")) for i in (1, 2)]
            )
            return [float(np.linalg.norm(points[a] - points[b])) for a, b in pairs]

        report = {
            "qualification": "experimental vacuum minimization; provisional parameters",
            "neighbor_backbones_mobile": args.neighbor_backbones,
            "steps": args.steps,
            "engine": engine,
            "energy": _energy_audit(out / "minimize.log"),
            "chirality_before": chirality(xyz),
            "chirality_after": chirality(final),
            "boundary_bonds_before_A": lengths(xyz, "boundary"),
            "boundary_bonds_after_A": lengths(final, "boundary"),
            "glyco_after_A": lengths(final, "glyco"),
            "max_fixed_displacement_A": float(
                np.linalg.norm(final[~mobile] - xyz[~mobile], axis=1).max()
            ),
            "mobile_rms_displacement_A": float(
                np.sqrt(np.mean(np.sum((final[mobile] - xyz[mobile]) ** 2, axis=1)))
            ),
        }
        write(out / "report.json", report)
        print(
            core["id"],
            json.dumps(
                {
                    k: report[k]
                    for k in [
                        "boundary_bonds_after_A",
                        "glyco_after_A",
                        "max_fixed_displacement_A",
                    ]
                }
            ),
            "chirality",
            report["chirality_after"]["passed"],
            flush=True,
        )


if __name__ == "__main__":
    main()
