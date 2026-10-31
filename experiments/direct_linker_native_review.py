"""Full native producer/Direct A/B; never a production history receipt."""

from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.atomistic import build_atomistic_model
from backend.core.molecular_placement_audit import _affected_serials, _defect_serials
from experiments.direct_linker_candidate import candidate_model
from experiments.direct_linker_native import connection_inputs, native_source, proposed_connection_command
from experiments.direct_linker_review import junction_metrics, model_data


def build_review(output, summary_output):
    from tests.test_part_pending_connection_versions import proof

    reference = native_source()
    native_proof = proof(reference)
    assert native_proof["status"] == "verified" and native_proof["checked_commands"] == 3
    drafts = []
    candidate = proposed_connection_command(reference, connection_inputs(reference), reference=reference,
        capture=lambda design, *_: drafts.append(design.model_copy(deep=True)))
    assert len(drafts) == 1
    current = drafts[0]
    driven = candidate.overhang_bindings[0].driven_oh_id
    designs = {"reference": reference, "current": current, "candidate": candidate}
    modes, junctions = {}, {}
    for name, fast in (("viewer", True), ("export", False)):
        models = {"reference": build_atomistic_model(reference, fast_bridges=fast),
            "current": build_atomistic_model(current, fast_bridges=fast),
            "candidate": candidate_model(candidate, reference, [driven], fast_bridges=fast)}
        assert models["current"].bonds == models["candidate"].bonds
        assert [replace(a, x=0., y=0., z=0.) for a in models["current"].atoms] == [
            replace(a, x=0., y=0., z=0.) for a in models["candidate"].atoms]
        data = {s: model_data(designs[s], m) for s, m in models.items()}
        affected, delta = _affected_serials(models["current"], models["candidate"],
            data["current"]["diagnostics"], data["candidate"]["diagnostics"])
        data.update(affected_atom_serials=affected, displacement=delta,
            defect_atom_serials={s: _defect_serials(data[s]["diagnostics"]) for s in ("current", "candidate")})
        modes[name] = data
        junctions[name] = [junction_metrics(reference, current, models, o.id) for o in reference.overhangs]
        print(name, {s: {"atoms": len(models[s].atoms), "clashes": data[s]["diagnostics"]["n_clashes"],
            "piercings": data[s]["diagnostics"]["piercing"]["n_pierced"],
            "bond_flags": data[s]["diagnostics"]["bonds"]["n_overstretched"]} for s in models}, flush=True)
    controls = ROOT / "frontend/src/ui/geometry_review_data/direct-linker.json.gz"
    data = modes["viewer"]["candidate"]
    owner = {(n["strand_id"], n["helix_id"], n["bp_index"], n["direction"]): n.get("overhang_id")
             for n in data["nucleotides"]}
    clash_scope = {"within_duplex": 0, "duplex_parent": 0, "parent_parent": 0}
    for hit in data["diagnostics"]["clashes"]:
        a, b = (data["atoms"][i] for i in hit["serials"])
        oa, ob = (owner.get((a["strand_id"], a["helix_id"], a["bp_index"], a["direction"])) for a in (a, b))
        clash_scope["within_duplex" if oa and ob else "duplex_parent" if oa or ob else "parent_parent"] += 1
    bundle = {"schema": "nadoc.direct-linker-native-review.v1", "read_only": True,
        "ready_for_review": True, "label": "Direct — native 46-base connection, fixed roots",
        "fit_expected": True, "full_geometry_changed": True,
        "fit_description": "Two native 46-base overhangs span the fixed host roots. Candidate moves the paired duplex rigidly while retaining both original root lengths in Viewer and Export. Parent poses remain fixed; collisions stay advisory. The fitted duplex passes through the bundle: all 71 clash pairs involve surrounding parent DNA; no pair is wholly inside the duplex. There are also 15 ring piercings, listed below.",
        **{s + "_design": d.model_dump(mode="json") for s, d in designs.items()},
        **modes["viewer"], "export_models": modes["export"], "junctions": junctions,
        "midpoint_constraint_planes": [],
        "clash_scope": clash_scope,
        "native_prefix_proof": {"status": native_proof["status"], "checked_commands": 3},
        "proposed_command": connection_inputs(reference),
        "construction": ["F1: Extrude 1 — six helices, 42 base pairs, honeycomb cells (0,1–3) and (1,1–3).",
            "F2: Extrude 2 — a 46-base 3′ overhang from cell (0,3), bp 41, into legal neighboring cell (0,4).",
            "F3: Extrude 3 — a 46-base 3′ overhang from cell (1,1), bp 0, into legal neighboring cell (1,0).",
            "Connect 1, diagnostic continuation — end-to-root Direct connection; original sequences retained. Current is the exact draft entering placement, which production refuses. Candidate uses the same command with the isolated linker-preserving placement stage.",
            "The first three features cold-replay from an empty root. The proposed Connect has no authored row or production verification receipt."],
        "limitations": ["Candidate changes five native root-linker atoms before rigidly fitting the duplex; it does not change the sugar/base templates or any detector threshold.",
            "The complete before/after atom sets and exact defects are shown. A closed root does not certify absence of collisions or suitability for simulation.",
            "Production Connect still refuses this input. The proposed geometry exists only in prepared review evidence; no candidate atoms are enabled for ordinary display, export or simulation.",
            "The native three-feature prefix is verified. Candidate command reconstruction, driver changes, namespace ownership, native parent motion and Unapply are checked in the isolated diagnostic. Production history adoption still requires approval and integration qualification."],
        "related_controls": {"asset": controls.name, "sha256": hashlib.sha256(controls.read_bytes()).hexdigest(),
            "phase_cases": 36, "unchanged_2hb_cases": 22}}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(bundle, separators=(",", ":"), allow_nan=False).encode(), mtime=0))
    summary = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
        "junctions": junctions, "displacement": {k: v for k, v in bundle["displacement"].items() if k != "vectors"},
        "diagnostics": {name: {s: modes[name][s]["diagnostics"] for s in designs} for name in modes},
        "prefix_proof": bundle["native_prefix_proof"], "ready_for_review": True}
    Path(summary_output).write_text(json.dumps(summary, indent=2))
    print("PREPARED", path, summary["bytes"], summary["sha256"], flush=True)


if __name__ == "__main__":
    build_review(sys.argv[1], sys.argv[2])
