"""Prepare full-context, diagnostic-only Direct linker A/B evidence."""

from __future__ import annotations

from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from backend.core.atomistic import atomistic_to_json, build_atomistic_model
from backend.core.design_geometry import fitting_geometry
from backend.core.molecular_placement_audit import _affected_serials, _defect_serials, _model_diagnostics
from experiments.direct_linker_candidate import candidate_model, positions, residue, root_endpoints, root_residues
from tests.test_direct_linker_candidate import reachable_crossover_source, relocate


def model_data(design, model):
    data = atomistic_to_json(model)
    # Keep full precision in the evidence; the generic display serializer rounds.
    data["atoms"] = [asdict(a) for a in model.atoms]
    data["diagnostics"] = _model_diagnostics(design, model)
    if data["diagnostics"]["n_clashes"] >= 200 or data["diagnostics"]["bonds"]["n_overstretched"] > 200:
        raise ValueError("Evidence exceeds the existing diagnostic report cap")
    data["nucleotides"] = fitting_geometry(design)
    return data


def junction_metrics(original, relocated, models, oid):
    old, new = root_residues(original, oid), root_residues(relocated, oid)
    roots, adjacent, angles, deltas = {}, [], [], []
    for side, model in models.items():
        design = original if side == "reference" else relocated
        root = root_endpoints(design, model, oid)
        roots[side] = {"length_nm": root["length_nm"], "serials": root["serials"]}
    for half, bonds in enumerate(((("C3'", "O3'"),),
                                  (("C5'", "O5'"), ("O5'", "P"), ("P", "OP1"), ("P", "OP2")))):
        residues = {side: residue(m.atoms, (old if side == "reference" else new)[half])
                    for side, m in models.items()}
        for names in bonds:
            values = {}
            for side, atoms in residues.items():
                xyz = positions([atoms[n] for n in names])
                values[side] = {"length_nm": float(np.linalg.norm(xyz[0] - xyz[1])),
                                "serials": [atoms[n].serial for n in names]}
            adjacent.append({"names": names, "values": values})
        triplets = (("O3'", "C3'", "C4'"), ("O3'", "C3'", "C2'")) if half == 0 else (
            ("O5'", "C5'", "C4'"), ("P", "O5'", "C5'"), ("OP1", "P", "O5'"), ("OP2", "P", "O5'"))
        for names in triplets:
            values = {}
            for side, atoms in residues.items():
                a, b, c = positions([atoms[n] for n in names])
                x, y = a - b, c - b
                values[side] = float(np.degrees(np.arccos(np.clip(np.dot(x, y) / np.linalg.norm(x) / np.linalg.norm(y), -1., 1.))))
            angles.append({"names": names, "degrees": values})
        for name, atom in residues["candidate"].items():
            other = residues["current"][name]
            delta = float(np.linalg.norm(positions([atom])[0] - positions([other])[0]))
            if delta > 1e-10:
                deltas.append({"serial": atom.serial, "name": name, "distance_nm": delta})
    return {"overhang_id": oid, "roots": roots, "adjacent_bonds": adjacent,
            "adjacent_angles": angles, "atom_deltas": deltas,
            "max_adjacent_bond_change_from_reference_nm": max(abs(r["values"]["candidate"]["length_nm"]
                - r["values"]["reference"]["length_nm"]) for r in adjacent)}


def comparison(original, *, label, construction, fit_expected):
    raw = relocate(original)
    driven = original.overhangs[1].id
    models = {"reference": build_atomistic_model(original, fast_bridges=True),
              "current": build_atomistic_model(raw, fast_bridges=True),
              "candidate": candidate_model(raw, original, [driven], fast_bridges=True)}
    data = {side: model_data(original if side == "reference" else raw, model)
            for side, model in models.items()}
    affected, displacement = _affected_serials(models["current"], models["candidate"],
        data["current"]["diagnostics"], data["candidate"]["diagnostics"])
    junctions = {"viewer": [junction_metrics(original, raw, models, o.id) for o in original.overhangs]}
    export_models = {"reference": build_atomistic_model(original, fast_bridges=False),
                     "current": build_atomistic_model(raw, fast_bridges=False),
                     "candidate": candidate_model(raw, original, [driven], fast_bridges=False)}
    junctions["export"] = [junction_metrics(original, raw, export_models, o.id) for o in original.overhangs]
    export_data = {side: model_data(original if side == "reference" else raw, model)
                   for side, model in export_models.items()}
    export_affected, export_displacement = _affected_serials(export_models["current"], export_models["candidate"],
        export_data["current"]["diagnostics"], export_data["candidate"]["diagnostics"])
    export_data.update(affected_atom_serials=export_affected, displacement=export_displacement,
        defect_atom_serials={s: _defect_serials(export_data[s]["diagnostics"]) for s in ("current", "candidate")})
    if models["current"].bonds != models["candidate"].bonds:
        raise ValueError("Candidate changed molecular connectivity")
    def pairs(side):
        return {tuple(sorted(h["serials"])) for h in data[side]["diagnostics"]["clashes"]}
    return {"schema": "nadoc.direct-linker-review.v1", "read_only": True,
        "ready_for_review": False, "label": label, "construction": construction,
        "fit_expected": fit_expected, "reference_design": original.model_dump(mode="json"),
        "current_design": raw.model_dump(mode="json"), "candidate_design": raw.model_dump(mode="json"),
        **data, "export_models": export_data, "junctions": junctions,
        "affected_atom_serials": affected, "displacement": displacement,
        "defect_atom_serials": {s: _defect_serials(data[s]["diagnostics"]) for s in ("current", "candidate")},
        "midpoint_constraint_planes": [],
        "clash_changes": {"introduced": sorted(pairs("candidate") - pairs("current")),
                          "removed": sorted(pairs("current") - pairs("candidate"))},
        "limitations": ["Current is the raw relocated draft; production refuses it before publishing.",
            "Candidate preserves pre-connection linker atoms. Native rings and bases stay unchanged.",
            "The displayed draft has no automatic body motion. Root lengths remain fixed only in a feasible layout.",
            "Native bond defects are retained, not chemically repaired. Repositioned-overhang collisions are advisory.",
            "Snapshot restoration, edited parent deformations, branch/clone and native full-history integration remain unqualified.",
            "Candidate atoms exist only in this review; ordinary display, export and simulation remain unchanged."]}


def build_review(output, summary_output=None):
    from tests.test_part_pending_connection_versions import native_prefix
    from tests.reciprocal_design import reciprocal_design

    source = reachable_crossover_source()
    bundle = comparison(source, label="Direct — preserved root linker (isolated draft)", fit_expected=True,
        construction=["Imported diagnostic: two staple strands, each with a four-base parent and a terminal overhang (8 and 4 bases). All four helices are shown.",
            "Diagnostic setup — Make Cluster: parent B and its unbound overhang form one rigid body. This imported fixture has no authored history row.",
            "Diagnostic setup — Move/Rotate: place body B by matching the driven root sugar frame to the intended paired position. Its root length is unchanged.",
            "Connect: relocate the four-base overhang onto the opposite strand of the eight-base overhang. Current shows this raw draft, refused by production.",
            "Candidate diagnostic: carry the original O3′ and P/OP1/OP2/O5′ linker groups with their adjacent sugars. No authored feature or particle motion is added."])
    native = native_prefix.__wrapped__()
    bundle["controls"] = {"native": comparison(native, label="Native Extrude — unreachable parent layout", fit_expected=False,
        construction=["F1: Extrude 1 — six helices, 42 base pairs, honeycomb lattice.",
            "F2: Extrude 2 — 12-base 3′ overhang at the first valid native site.",
            "F3: Extrude 3 — 12-base 5′ overhang at the first valid native site; both overhangs share a host strand.",
            "Connect diagnostic: relocate the second overhang. The distant parent roots remain unreachable; preserving linker atoms does not authorize this connection."])}
    sweep = []
    for phase in range(0, 360, 10):
        original = reachable_crossover_source(phase)
        raw = relocate(original)
        row = {"phase_deg": phase, "builders": {}}
        for fast, name in ((True, "viewer"), (False, "export")):
            models = {"reference": build_atomistic_model(original, fast_bridges=fast),
                "current": build_atomistic_model(raw, fast_bridges=fast),
                "candidate": candidate_model(raw, original, ["oh-b"], fast_bridges=fast)}
            junctions = [junction_metrics(original, raw, models, o.id) for o in original.overhangs]
            diag = {s: _model_diagnostics(original if s == "reference" else raw, models[s])
                    for s in ("reference", "current", "candidate")}
            row["builders"][name] = {"junctions": junctions, "diagnostics": diag}
        sweep.append(row)
    bundle["phase_sweep"] = sweep
    bundle["controls"]["contact"] = comparison(reachable_crossover_source(270),
        label="Direct — phase control with retained atom contact", fit_expected=True,
        construction=[*bundle["construction"],
            "Engineering control: repeat at 270° helix phase, retaining all atoms and the exact detected contact pair."])
    unchanged = []
    for extra in ("T", "TT"):
        for bp in range(8, 19):
            design = reciprocal_design(extra, bp=bp)
            current = build_atomistic_model(design, fast_bridges=False)
            candidate = candidate_model(design, design, [], fast_bridges=False)
            if current != candidate:
                raise ValueError("Unrelated reciprocal 2HB geometry changed")
            data = model_data(design, current)
            verdict = "pierced" if data["diagnostics"]["piercing"]["n_pierced"] else "clear"
            unchanged.append({"extra_bases": extra, "bp": bp, "verdict": verdict,
                "identical": True, "diagnostics": data["diagnostics"]})
            if verdict not in bundle["controls"]:
                bundle["controls"][verdict] = {"read_only": True, "ready_for_review": False,
                    "label": f"Unchanged 2HB {verdict} control", "current": data, "candidate": data,
                    "current_design": design.model_dump(mode="json"), "candidate_design": design.model_dump(mode="json"),
                    "affected_atom_serials": [], "defect_atom_serials": {s: _defect_serials(data["diagnostics"]) for s in ("current", "candidate")},
                    "displacement": {"n_displaced": 0, "max_nm": 0, "rms_nm": 0, "vectors": []},
                    "midpoint_constraint_planes": []}
    bundle["unchanged_2hb_sweep"] = unchanged
    encoded = json.dumps(bundle, separators=(",", ":"), allow_nan=False).encode()
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(encoded, mtime=0))
    summary = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
        "atoms": len(bundle["current"]["atoms"]), "displacement": {k: v for k, v in bundle["displacement"].items() if k != "vectors"},
        "clash_changes": bundle["clash_changes"], "junctions": bundle["junctions"],
        "phase_cases": len(sweep), "unchanged_2hb_cases": len(unchanged),
        "ready_for_review": False}
    if summary_output is not None:
        Path(summary_output).write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "junctions"}), flush=True)


if __name__ == "__main__":
    build_review(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
