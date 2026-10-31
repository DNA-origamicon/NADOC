"""File-level A/B review of isolated paired-Fine atomic transport; no dynamics."""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import html
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.atomistic import build_atomistic_model
from backend.core.deformation import effective_helix_for_geometry
from backend.core.models import Design
from backend.core.molecular_placement_audit import _affected_serials, _model_diagnostics
from backend.core.mrdna_runner import build_md_seed_override
from experiments.mrdna_frame_qualification import atom_identity, xyz
from experiments.mrdna_frame_review_figure import junction_defects, render_plate
from experiments.mrdna_seed_candidate import native_reference
from experiments.mrdna_seed_transport_candidate import reconstruct
from scripts.run_deformation_history_e2e import storage_parent


def prescribed(reference, mode):
    seed = reference["particles"]
    final = seed.copy()
    expected = xyz(reference["model"])
    if mode == "rigid":
        rotation = Rotation.from_euler("xyz", [17, -31, 67], degrees=True).as_matrix()
        final = seed @ rotation.T + [2.1, -0.9, 3.4]
        # Production seeds remove global drift. Native atoms are the independent target.
    elif "twist" in mode:
        sites = {(r.render.helix_id, r.render.bp_index): r.particle_bindings[0].particle_index
                 for r in reference["manifest"].records}
        rotations = {}
        for key, index in sites.items():
            bps = sorted(bp for hid, bp in sites if hid == key[0])
            at = bps.index(key[1])
            tangent = (seed[sites[key[0], bps[min(at + 1, len(bps) - 1)]]]
                       - seed[sites[key[0], bps[max(at - 1, 0)]]])
            rotation = Rotation.from_rotvec(tangent / np.linalg.norm(tangent)
                * np.deg2rad(12 * np.sin(key[1] / 7))).as_matrix()
            final[index + 1] = seed[index] + rotation @ (seed[index + 1] - seed[index])
            rotations[key] = rotation
        expected = np.array([
            seed[sites[a.helix_id, a.bp_index]] + rotations[a.helix_id, a.bp_index]
            @ (point - seed[sites[a.helix_id, a.bp_index]])
            for a, point in zip(reference["model"].atoms, expected)
        ])
    return final, expected


def qualify(output, phases):
    import MDAnalysis as mda

    output.mkdir(parents=True, exist_ok=True)
    source = Path("Examples/2hb_xover_val.nadoc")
    original = Design.model_validate_json(source.read_text())
    original_snapshot = original.model_dump_json()
    original_xyz = xyz(build_atomistic_model(original))
    parent = storage_parent()
    if shutil.disk_usage(parent).free < 1024**3:
        raise RuntimeError("Insufficient scratch space for isolated review")
    rows = []
    with tempfile.TemporaryDirectory(prefix="mt-", dir=parent) as temporary:
        scratch = Path(temporary)
        for phase in phases:
            design = original.model_copy(deep=True)
            design.helices = [effective_helix_for_geometry(h, original).model_copy(update={
                "grid_pos": None,
                "phase_offset": effective_helix_for_geometry(h, original).phase_offset + np.deg2rad(phase),
            }) for h in original.helices]
            snapshot = design.model_dump_json()
            reference = native_reference(design)
            native = reference["model"]
            native_xyz = xyz(native)
            if phase == 0:
                np.testing.assert_allclose(native_xyz, original_xyz, atol=1e-12, rtol=0)
            elif np.max(np.linalg.norm(native_xyz - original_xyz, axis=1)) < 0.01:
                raise AssertionError("Diagnostic phase was erased by normalization")
            identity = [atom_identity(a) for a in native.atoms]
            psf, pdb = scratch / "fine.psf", scratch / "fine.pdb"
            psf.write_text(reference["psf_text"])
            restart_reference = None
            for mode in ("zero_pdb", "zero_dcd", "rigid", "local_twist", "restart_twist"):
                pdb.write_text(reference["pdb_text"])
                final, expected = prescribed(reference, mode)
                universe = mda.Universe(str(psf), str(pdb))
                try:
                    universe.atoms.positions = final * 10
                    if mode == "restart_twist":
                        universe.atoms.write(str(pdb))
                    trajectory = scratch / "frame.dcd"
                    with mda.Writer(str(trajectory), n_atoms=len(universe.atoms)) as writer:
                        writer.write(universe.atoms)
                finally:
                    universe.trajectory.close()
                if mode == "zero_pdb":
                    trajectory = pdb
                candidate = reconstruct(reference, psf, trajectory)["model"]
                current = build_atomistic_model(design,
                    nuc_pos_override=build_md_seed_override(design, psf, trajectory),
                    apply_design_geometry=False)
                models = {"reference": native, "current": current, "candidate": candidate}
                positions = {side: xyz(model) for side, model in models.items()}
                for model in models.values():
                    assert [atom_identity(a) for a in model.atoms] == identity
                    assert model.bonds == native.bonds
                error = np.linalg.norm(positions["candidate"] - expected, axis=1)
                if mode.startswith("zero"):
                    np.testing.assert_array_equal(positions["candidate"], native_xyz)
                # A float32 DCD stores Å coordinates. This additional precision
                # control is much tighter than the retained 0.10/0.25-nm oracle;
                # it is not a change to any production detector or existing test.
                assert max(error) < 5e-5, (phase, mode, max(error))
                restart_error = None
                if mode == "local_twist":
                    restart_reference = positions["candidate"].copy()
                if mode == "restart_twist":
                    restart_error = float(np.max(np.linalg.norm(
                        positions["candidate"] - restart_reference, axis=1)))
                    np.testing.assert_array_equal(positions["candidate"], restart_reference)
                diagnostics = {side: _model_diagnostics(design, model) for side, model in models.items()}
                affected, displacement = _affected_serials(current, candidate,
                    diagnostics["current"], diagnostics["candidate"])
                junctions = [{
                    "serials": [i, j], "identities": [identity[i], identity[j]],
                    "length_nm": {s: float(np.linalg.norm(p[i] - p[j])) for s, p in positions.items()},
                    "max_endpoint_displacement_nm": float(max(np.linalg.norm(
                        positions["candidate"][k] - positions["current"][k]) for k in (i, j))),
                    "defects": {s: junction_defects(m, diagnostics[s], (i, j)) for s, m in models.items()},
                } for i, j in native.bonds if native.atoms[i].helix_id != native.atoms[j].helix_id]
                name = f"phase-{phase:03d}-{mode}.json.gz"
                bundle = {
                    "phase_deg": phase, "motion": mode, "read_only": True,
                    "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "figure_title": f"mrDNA seed reconstruction: {mode}, phase {phase}°\n"
                        "Current: production seed. Candidate: isolated native atom transport. No dynamics.",
                    "affected_atom_serials": affected, "displacement": displacement,
                    "junctions": junctions,
                    **{s: {"atoms": [asdict(a) for a in m.atoms], "bonds": m.bonds,
                           "diagnostics": diagnostics[s]} for s, m in models.items()},
                }
                with gzip.open(output / name, "wt") as stream:
                    json.dump(bundle, stream, separators=(",", ":"))
                row = {"phase_deg": phase, "motion": mode, "artifact": name,
                       "all_atom_max_error_nm": float(max(error)),
                       "restart_vs_direct_nm": restart_error,
                       "current_diagnostics": diagnostics["current"],
                       "candidate_diagnostics": diagnostics["candidate"],
                       "junctions": junctions}
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items()
                                  if k not in {"current_diagnostics", "candidate_diagnostics", "junctions"}}), flush=True)
                assert design.model_dump_json() == snapshot
            assert reference["scratch_absent"]
        size = sum(p.stat().st_size for p in scratch.rglob("*") if p.is_file())
    assert original.model_dump_json() == original_snapshot
    report = {"rows": rows, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "code_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (
                  Path(__file__), Path("experiments/mrdna_seed_transport_candidate.py"),
                  Path("experiments/mrdna_seed_candidate.py"), Path("backend/core/mrdna_bridge.py"),
                  Path("backend/core/mrdna_runner.py"), Path("backend/core/atomistic.py"))},
              "cleanup": {"path": str(scratch), "bytes_removed": size, "absent": not scratch.exists()},
              "limits": ["No dynamics; prescribed-motion software controls only.",
                         "Fully paired direct fine sites in an unposed snapshot only.",
                         "Unpaired, inserted, coarse, interpolated and posed designs remain unsupported.",
                         "Native bond strain and contacts are retained; this is not a physical-validity claim.",
                         "Production, its existing accuracy oracle and all geometry locks remain unchanged."]}
    (output / "qualification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def build_review(output, report):
    rows = report["rows"]
    choices = [next(r for r in rows if r["motion"] == mode) for mode in
               ("zero_dcd", "rigid", "local_twist", "restart_twist")]
    for kind in ("clashes", "piercings", "bond_flags"):
        def count(row, side):
            d = row[f"{side}_diagnostics"]
            return (d["n_clashes"] if kind == "clashes" else
                    d["piercing"]["n_pierced"] if kind == "piercings" else
                    d["bonds"]["n_overstretched"])
        for row in (min(rows, key=lambda r: count(r, "candidate") - count(r, "current")),
                    max(rows, key=lambda r: count(r, "candidate") - count(r, "current"))):
            if row not in choices:
                choices.append(row)
    sections = []
    for row in choices:
        with gzip.open(output / row["artifact"], "rt") as stream:
            bundle = json.load(stream)
        png = f"phase-{row['phase_deg']:03d}-{row['motion']}.png"
        render_plate(bundle, output / png)
        records = []
        for j in bundle["junctions"]:
            values = [j["serials"], *(f"{j['length_nm'][s]:.6f}" for s in
                      ("reference", "current", "candidate")),
                      f"{j['max_endpoint_displacement_nm']:.6f}",
                      f"{j['length_nm']['candidate'] - j['length_nm']['current']:+.6f}",
                      *(f"{len(j['defects']['current'][k])} → {len(j['defects']['candidate'][k])}"
                        for k in ("clashes", "piercings"))]
            records.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in values) + "</tr>")
        sections.append(f"<section><h2>{row['motion']}; phase {row['phase_deg']}°</h2>"
            f"<p>Max error against prescribed native-atom motion: {row['all_atom_max_error_nm']:.9g} nm. "
            f"<a href='{row['artifact']}'>All atoms, bonds and exact detector hits</a>.</p>"
            f"<img src='{png}' alt='Current, Candidate, displacement overlay and exact defect close-up'>"
            "<table><tr><th>Junction atoms</th><th>Native nm</th><th>Current nm</th>"
            "<th>Candidate nm</th><th>Max endpoint displacement nm</th><th>Δ bond nm</th>"
            "<th>Clashes</th><th>Piercings</th></tr>" + "".join(records) + "</table></section>")
    metrics = []
    for mode in ("zero_pdb", "zero_dcd", "rigid", "local_twist", "restart_twist"):
        group = [r for r in rows if r["motion"] == mode]
        metrics.append(f"<tr><td>{mode}</td><td>{len(group)}</td>"
                       f"<td>{max(r['all_atom_max_error_nm'] for r in group):.9g}</td></tr>")
    limits = "".join(f"<li>{html.escape(line)}</li>" for line in report["limits"])
    page = ("<!doctype html><meta charset='utf-8'><title>mrDNA native atom transport review</title>"
        "<style>body{font:16px system-ui;max-width:1500px;margin:2rem auto;padding:1rem}"
        "img{width:100%}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.4rem}"
        "section{margin:2rem 0}li{margin:.5rem 0}</style>"
        "<h1>mrDNA → NAMD: native atom transport</h1>"
        "<p><strong>Isolated molecular candidate. Production and its tests are unchanged.</strong></p>"
        "<p>Current is NADOC's production seed reconstruction with its default smoothing. Candidate carries "
        "the existing native atoms through measured Fine-particle frame changes; it does not rebuild linker "
        "atoms. Both are shown in the original design frame, before final NAMD origin-centering.</p>"
        "<h2>Construction and the difference to inspect</h2><ol>"
        "<li>File → Open: Examples/2hb_xover_val.nadoc, the existing two-helix validation design. "
        "Its covalent graph is retained. No new feature-log actions are authored.</li>"
        "<li>Diagnostic program only: generate the native Fine PSF/PDB, then write prescribed trajectory "
        "frames. No Run mrDNA relaxation, NAMD preparation or simulation is launched.</li>"
        "<li>Controls: identical PDB; identical DCD; a 17°, −31°, 67° rigid rotation and "
        "(2.1, −0.9, 3.4) nm translation; local O-particle twist with DNA centers fixed; the same twist "
        "already present in the fine-stage restart PDB. The last two must reconstruct identically.</li>"
        "<li>Current uses the implemented seed reader. Candidate measures DNA-center drift separately "
        "from O-particle twist and transports native atoms by the resulting local frames.</li>"
        "<li>In zero and rigid controls, look for preservation of every native atom, including P/O3′. "
        "In twist controls, inspect changed covalent junctions and the highlighted contacts/rings. "
        "Native strain is retained; lower contact counts do not establish physical validity.</li></ol>"
        "<p>The engineering phase sweep resolves native helix frames and rolls them through one full turn "
        "in diagnostic copies only. Phase zero is checked against the original native atoms. "
        "No swept design, new history, geometry lock or simulation input is saved.</p>"
        "<h2>Prescribed-motion checks through actual files</h2><table><tr><th>Control</th>"
        "<th>Phases</th><th>Maximum atom error nm</th></tr>" + "".join(metrics) + "</table>"
        + "".join(sections[:4])
        + "<details><summary>Positive and negative phase controls</summary>" + "".join(sections[4:])
        + "</details><h2>Limits</h2><ul>" + limits
        + "</ul><p><a href='qualification.json'>All phase/motion metrics, junctions and source hashes</a></p>")
    (output / "review.html").write_text(page)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phases", type=int, nargs="+", default=list(range(0, 360, 10)))
    args = parser.parse_args()
    build_review(args.output, qualify(args.output, args.phases))
