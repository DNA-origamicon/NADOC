"""Isolated terminal-tail representation hypotheses; no production policy."""
import math
from copy import deepcopy
from dataclasses import fields
from uuid import UUID

import numpy as np

from backend.api import crud
from backend.core import models as m
from backend.core.atomistic import Atom, atomistic_to_json, build_atomistic_model
from backend.core.base_keys import atom_base_key
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.molecular_placement_audit import _affected_serials, _defect_serials, _model_diagnostics
from backend.core.part_history_contract import create_empty_part
from tests.test_part_deformation_preview import _append
from tests.test_part_motion_native_characterization import _expected_point, _PIVOT, _ROTATION, _TRANSLATION
from tests.test_part_transform_inputs import pose
from tests.test_part_transform_preview import snapshot
from tools.member_motion_audit import _junction_rows, roll_native_source


def tail_source(end, direction, phase_deg):
    source = snapshot(create_empty_part("Tail representation probe", "HONEYCOMB"), "bundle-create",
                      crud.BundleRequest(cells=[[0, 0], [1, 0]], length_bp=8, ligate_adjacent=False,
                                         history_seed=UUID(int=16001)).model_dump(mode="json"), "native-bundle")
    helix_id = source.helices[0].id
    source = roll_native_source(source, helix_id, phase_deg)
    selected = next(s for s in source.strands
                    if s.domains[0].helix_id == helix_id and s.domains[0].direction == direction)
    control = next(s for s in source.strands
                   if s.domains[0].helix_id == helix_id and s.id != selected.id)
    entries = [{"create": True, "extension": {
        "id": identity, "strand_id": strand.id, "end": end,
        "sequence": "AC", "modification": None, "label": identity,
    }} for identity, strand in (("selected-tail", selected), ("control-tail", control))]
    source = _append(source, m.SnapshotLogEntry(
        id="native-tails", op_kind="extension-upsert", label="Native terminal tails",
        params={"_proof_version": 2, "entries": entries}, evicted=True,
        design_snapshot_gz_b64="unusable-recovery", post_state_gz_b64="unusable-recovery"))
    domain = selected.domains[0] if end == "five_prime" else selected.domains[-1]
    bp = domain.start_bp if end == "five_prime" else domain.end_bp
    return source, (domain.helix_id, bp, domain.direction.value, 0)


def build_tail_case(phase_deg=0, direction="FORWARD", end="five_prime", hypothesis="full-follows"):
    if hypothesis not in {"full-follows", "atoms-stay"}:
        raise ValueError("Unknown isolated hypothesis")
    source, target = tail_source(end, m.Direction(direction), phase_deg)
    captured = source.model_dump_json()
    changed = snapshot(source, "nucleotide-transform", {
        **pose(helix_id=target[0], bp_index=target[1], direction=target[2],
               rotation=[0, 0, math.sqrt(0.5), math.sqrt(0.5)],
               pivot=_PIVOT.tolist(), translation=_TRANSLATION.tolist()),
        "history_seed": str(UUID(int=16002)),
    }, "terminal-residue-pose")
    current = build_atomistic_model(changed, fast_bridges=True)
    before = build_atomistic_model(source, fast_bridges=True)
    candidate = deepcopy(current)
    full = _geometry_for_design(changed)
    candidate_full = deepcopy(full)
    identity = [f.name for f in fields(Atom) if f.name not in {"x", "y", "z"}]
    assert current.bonds == before.bonds
    assert [tuple(getattr(a, f) for f in identity) for a in current.atoms] == [
        tuple(getattr(a, f) for f in identity) for a in before.atoms]
    if hypothesis == "full-follows":
        for row in candidate_full:
            if row.get("extension_id") != "selected-tail":
                continue
            assert row["slab_position"] is None and row["slab_quaternion"] is None
            assert not row.get("helical_site")
            for name in ("backbone_position", "base_position"):
                row[name] = _expected_point(row[name]).tolist()
            for name in ("base_normal", "axis_tangent"):
                row[name] = (_ROTATION @ row[name]).tolist()
    else:
        for old, atom in zip(before.atoms, candidate.atoms, strict=True):
            if atom.extension_id == "selected-tail":
                atom.x, atom.y, atom.z = old.x, old.y, old.z
    full_vectors = []
    for old, new in zip(full, candidate_full, strict=True):
        if old.get("extension_id") != "selected-tail":
            assert old == new
        for field in ("backbone_position", "base_position"):
            distance = float(np.linalg.norm(np.asarray(new[field]) - old[field]))
            if distance > 1e-10:
                full_vectors.append({"material_key": f'{old["helix_id"]}:{old["bp_index"]}:{old["direction"]}',
                                     "field": field, "from": old[field], "to": new[field], "distance_nm": distance})
    diagnostics = [_model_diagnostics(changed, model) for model in (current, candidate)]
    affected, displacement = _affected_serials(current, candidate, *diagnostics)
    full_keys = {row["material_key"] for row in full_vectors}
    full_serials = sorted(set(affected) | {
        i for i, atom in enumerate(current.atoms) if atom_base_key(atom) in full_keys})
    sides = []
    axes = deformed_helix_axes(changed)
    for model, records, diagnostic in zip((current, candidate), (full, candidate_full), diagnostics, strict=True):
        payload = atomistic_to_json(model)
        for row, atom in zip(payload["atoms"], model.atoms, strict=True):
            row["material_key"] = atom_base_key(atom)
        sides.append({**payload, "nucleotides": records, "helix_axes": axes, "diagnostics": diagnostic})
    assert source.model_dump_json() == captured
    design = changed.model_dump(mode="json")
    return {
        "schema": "nadoc.member-motion-tail-audit.v1", "read_only": True,
        "case": {"phase_deg": phase_deg, "direction": direction, "end": end, "hypothesis": hypothesis},
        "provider": {
            "id": "detached-terminal-tail-hypothesis", "label": f"Tail hypothesis: {hypothesis}",
            "not_authorized_for_production": True,
            "panel_labels": {"current": "Current: Full stays / atoms follow",
                             "candidate": "Hypothesis: " + hypothesis},
            "panel_notes": {"current": "Existing terminal-pose discrepancy",
                            "candidate": "Isolated representation hypothesis — not authorized"}},
        "current_design": design, "candidate_design": deepcopy(design),
        "nucleotides": full, "helix_axes": axes, "current": sides[0], "candidate": sides[1],
        "affected_atom_serials": affected, "full_affected_atom_serials": full_serials,
        "displacement": displacement,
        "full_displacement": {"n_displaced": len(full_keys),
                              "max_nm": max((r["distance_nm"] for r in full_vectors), default=0),
                              "vectors": full_vectors},
        "defect_atom_serials": {side: _defect_serials(diag) for side, diag in zip(
            ("current", "candidate"), diagnostics, strict=True)},
        "junctions": _junction_rows(current, candidate, diagnostics),
        "diagnostic_limits": {"clash_hit_cap": 200, "overstretched_bond_row_cap": 200},
        "invariants": {"atom_identity": True, "bond_identity": True, "unselected_full_exact": True},
    }


def main():
    import argparse
    from html import escape
    import json
    from pathlib import Path
    import shutil

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--viewer-bundle", required=True, type=Path)
    parser.add_argument("--phase-step", type=int, default=10)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / ".development-artifacts"
    output = args.output.resolve()
    if not output.is_relative_to(root) or output.exists():
        parser.error("Expected a new directory under .development-artifacts")
    if args.phase_step < 5 or 360 % args.phase_step or shutil.disk_usage(root).free < 1024 ** 3:
        parser.error("Require phase step dividing 360 (at least 5) and 1 GiB free")
    viewer, css = args.viewer_bundle.read_bytes(), args.viewer_bundle.with_suffix(".css").read_bytes()
    if len(viewer) + len(css) > 8 * 1024 ** 2:
        parser.error("Viewer exceeds 8 MiB")
    output.mkdir()
    (output / "viewer.js").write_bytes(viewer)
    (output / "viewer.css").write_bytes(css)
    summaries, total = [], 0
    disclaimer = (
        "Isolated terminal-tail representation hypotheses, not approved placements. "
        "A moves only Full tail beads by the existing terminal pose, keeping atoms exact. "
        "B restores only tail atom coordinates from the exact native prefix, keeping Full exact. "
        "Neither reconstructs a tail or selects an attachment policy. Both use the same native 2HB input. "
        "Full and atomistic displacements are reported separately. Detector hit lists are capped at 200; "
        "local defect counts refer to reported hits. Phase offsets are fixture inputs, not replay claims.")
    for phase in range(0, 360, args.phase_step):
        for direction in ("FORWARD", "REVERSE"):
            for end in ("five_prime", "three_prime"):
                for hypothesis in ("full-follows", "atoms-stay"):
                    case = build_tail_case(phase, direction, end, hypothesis)
                    name = f"phase-{phase:03d}-{direction.lower()}-{end}-{hypothesis}"
                    text = json.dumps(case, separators=(",", ":"), allow_nan=False)
                    total += 2 * len(text.encode())
                    if total > 512 * 1024 ** 2:
                        raise ValueError("Evidence exceeds 512 MiB")
                    (output / f"{name}.json").write_text(text)
                    safe = text.replace("<", "\\u003c")
                    (output / f"{name}.html").write_text(
                        '<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="viewer.css">'
                        f'<title>{escape(name)}</title><a href="index.html">All phases</a>'
                        f'<h1>{escape(name)}</h1><p>{disclaimer}</p>'
                        '<button id="open-audit">Open comparison</button><div id="junctions"></div>'
                        f'<script>window.MOTION_AUDIT={safe}</script><script src="viewer.js"></script>')
                    summaries.append({"file": f"{name}.html", **case["case"],
                                      "atom_max_nm": case["displacement"]["max_nm"],
                                      "full_max_nm": case["full_displacement"]["max_nm"],
                                      "current": case["current"]["diagnostics"],
                                      "candidate": case["candidate"]["diagnostics"]})
        print(f"Recorded phase {phase}", flush=True)
    (output / "index.json").write_text(json.dumps(summaries, separators=(",", ":"), allow_nan=False))
    rows = "".join(f'<tr><td><a href="{r["file"]}">{r["file"][:-5]}</a></td>'
                   f'<td>{r["atom_max_nm"]:.6f}</td><td>{r["full_max_nm"]:.6f}</td></tr>' for r in summaries)
    (output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Terminal-tail representation review</title>'
        '<style>body{background:#0d1117;color:#ddd;font:16px sans-serif;margin:30px}'
        'a{color:#79c0ff}td,th{padding:8px;border-bottom:1px solid #444}</style>'
        f'<h1>Terminal-tail representation review</h1><p>{disclaimer}</p>'
        f'<p>0–360° phase sweep at {args.phase_step}° steps, both ends and directions.</p>'
        '<table><tr><th>Case</th><th>Max atom displacement nm</th><th>Max Full displacement nm</th></tr>'
        + rows + '</table>')
    print(f"Evidence: {output} ({total} bytes)", flush=True)


if __name__ == "__main__":
    main()
