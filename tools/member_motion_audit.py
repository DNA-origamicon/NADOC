"""Offline ordering evidence; never imported by display, export or simulation.

Compare native appended-owner placement with rigid world motion of exact native
prefix material. This deliberately excludes companions, birth, partial helices
and overlapping groups. It is an ordering probe, not an approved motion compiler.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import fields
from html import escape
import json
import math
from pathlib import Path
import shutil

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.atomistic import Atom, atomistic_to_json, build_atomistic_model
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Direction
from backend.core.molecular_placement_audit import (
    _affected_serials, _defect_serials, _model_diagnostics, _positions,
)
from tests.test_part_member_motion_order import D, M, N, _nucleotide, _owner, _source, _target


def _point(value, pose=M):
    pivot = np.asarray(pose["pivot"])
    return (Rotation.from_quat(pose["rotation"]).apply(np.asarray(value) - pivot)
            + pivot + pose["translation"]).tolist()


def _full_motion(records, helix_id):
    result = deepcopy(records)
    rotation = Rotation.from_quat(M["rotation"])
    for row in result:
        if row["helix_id"] != helix_id:
            continue
        for name in ("backbone_position", "base_position", "slab_position"):
            row[name] = _point(row[name])
        for name in ("base_normal", "axis_tangent"):
            row[name] = rotation.apply(row[name]).tolist()
        row["slab_quaternion"] = (rotation * Rotation.from_quat(row["slab_quaternion"])).as_quat().tolist()
        row["helical_site"]["axis_point"] = _point(row["helical_site"]["axis_point"])
        row["helical_site"]["radial_hat"] = rotation.apply(row["helical_site"]["radial_hat"]).tolist()
    return result


def _junction_rows(current, candidate, diagnostics):
    """Every inter-residue covalent bond, including the moved residue boundary."""
    before, after = _positions(current), _positions(candidate)
    rows = []
    for a, b in current.bonds:
        left, right = current.atoms[a], current.atoms[b]
        if (left.chain_id, left.seq_num) == (right.chain_id, right.seq_num):
            continue
        length_a = float(np.linalg.norm(before[a] - before[b]))
        length_b = float(np.linalg.norm(after[a] - after[b]))
        residues = {(left.chain_id, left.seq_num), (right.chain_id, right.seq_num)}
        members = {i for i, atom in enumerate(current.atoms) if (atom.chain_id, atom.seq_num) in residues}
        local = []
        for diagnostic in diagnostics:
            local.append({
                "clashes": [hit for hit in diagnostic["clashes"] if members.intersection(hit["serials"])],
                "piercings": [hit for hit in diagnostic["piercing"]["pierced"]
                             if members.intersection(hit["bond_serials"] + hit["ring_serials"])],
            })
        rows.append({"serials": [a, b], "names": [left.name, right.name],
                     "residues": [[left.chain_id, left.seq_num], [right.chain_id, right.seq_num]],
                     "current_length_nm": length_a, "candidate_length_nm": length_b,
                     "length_delta_nm": length_b - length_a,
                     "endpoint_displacement_nm": np.linalg.norm(after[[a, b]] - before[[a, b]], axis=1).tolist(),
                     "local_atom_serials": sorted(members), "current_defects": local[0], "candidate_defects": local[1],
                     "clash_delta": len(local[1]["clashes"]) - len(local[0]["clashes"]),
                     "piercing_delta": len(local[1]["piercings"]) - len(local[0]["piercings"])})
    return rows


def build_case(phase_deg=0, direction="FORWARD", *, prior_pose=True, chronological=False):
    """Native 2HB input; phase changes are confined to this disposable fixture."""
    source = _source()
    selected = source.helices[0].id
    source = source.copy_with(helices=[
        h.model_copy(update={"phase_offset": h.phase_offset + math.radians(phase_deg)})
        if h.id == selected else h for h in source.helices])
    _, target = _target(source, Direction(direction))
    prefix = _nucleotide(source, target, N, "prior-residue") if prior_pose else source
    source_json, prefix_json = source.model_dump_json(), prefix.model_dump_json()
    appended = _owner(prefix)
    event_trace = []
    if chronological:
        from tools.member_motion_ordering_program import compile_ordered_probe
        later = _nucleotide(prefix, target, D, "later-world-delta", compose=True)
        program = compile_ordered_probe(prefix, later.feature_log[-1], [selected])
        candidate_full, candidate, event_trace = program.evaluate()
        appended = _nucleotide(appended, target, D, "later-world-delta", compose=True)
    current = build_atomistic_model(appended, fast_bridges=True)
    if not chronological:
        prefix_atoms = build_atomistic_model(prefix, fast_bridges=True)
        candidate = deepcopy(prefix_atoms)
        for atom in candidate.atoms:
            if atom.helix_id == selected:
                atom.x, atom.y, atom.z = _point([atom.x, atom.y, atom.z])
    identity = [field.name for field in fields(Atom) if field.name not in {"x", "y", "z"}]
    if current.bonds != candidate.bonds or [
        tuple(getattr(atom, field) for field in identity) for atom in current.atoms
    ] != [tuple(getattr(atom, field) for field in identity) for atom in candidate.atoms]:
        raise ValueError("Ordering comparison changed native atom/bond identities")
    control = [i for i, atom in enumerate(current.atoms) if atom.helix_id != selected]
    np.testing.assert_array_equal(_positions(current)[control], _positions(candidate)[control])
    current_full = _geometry_for_design(appended)
    if not chronological:
        candidate_full = _full_motion(_geometry_for_design(prefix), selected)
    keys = ("helix_id", "bp_index", "direction", "copy_k", "strand_id", "domain_index", "overhang_id")
    assert [tuple(r.get(k) for k in keys) for r in current_full] == [
        tuple(r.get(k) for k in keys) for r in candidate_full]
    assert [r for r in current_full if r["helix_id"] != selected] == [
        r for r in candidate_full if r["helix_id"] != selected]
    diagnostics = [_model_diagnostics(appended, model) for model in (current, candidate)]
    affected, displacement = _affected_serials(current, candidate, *diagnostics)
    design = appended.model_dump(mode="json")
    axes = deformed_helix_axes(appended)  # whole-helix M is shared by both cases
    result = {
        "schema": "nadoc.member-motion-ordering-audit.v1", "read_only": True,
        "diagnostic_limits": {"clash_hit_cap": 200, "overstretched_bond_row_cap": 200,
                              "note": "Local defect counts use reported detector hits; capped lists are not exhaustive."},
        "case": {"phase_deg": phase_deg, "direction": direction, "prior_pose": prior_pose,
                 "selected_helix_id": selected, "selected_material": "whole helix, both directions",
                 "prior_N": N if prior_pose else None, "world_M": M,
                 "later_D": D if chronological else None},
        "event_trace": event_trace,
        "provider": {"id": "detached-native-prefix-world-motion",
                     "label": "Ordering probe: M(native prefix)",
                     "not_authorized_for_production": True,
                     "description": "Current appended owner versus detached chronological world motion. "
                                    "No tails, new material, partial helices or overlap policy is proposed."},
        "current_design": design, "candidate_design": deepcopy(design),
        "nucleotides": current_full, "helix_axes": axes,
        "current": {**atomistic_to_json(current), "diagnostics": diagnostics[0],
                    "nucleotides": current_full, "helix_axes": axes},
        "candidate": {**atomistic_to_json(candidate), "diagnostics": diagnostics[1],
                      "nucleotides": candidate_full, "helix_axes": deepcopy(axes)},
        "affected_atom_serials": affected, "displacement": displacement,
        "defect_atom_serials": {side: _defect_serials(diag) for side, diag in zip(
            ("current", "candidate"), diagnostics, strict=True)},
        "junctions": _junction_rows(current, candidate, diagnostics),
        "invariants": {"atom_identity": True, "bond_identity": True, "unselected_helix_exact": True,
                       "selected_atom_count": sum(a.helix_id == selected for a in candidate.atoms)},
    }
    if chronological:
        result["provider"].update({
            "id": "detached-native-prefix-chronological-motion",
            "label": "Chronological probe: N → M → D",
            "description": "Native appended owner plus later residue translation versus a bounded "
                           "detached chronological event program. No birth or companion policy.",
            "panel_labels": {"current": "Current: native D·N·M", "candidate": "Candidate: D·M·N"},
            "panel_notes": {"current": "Existing native owner and residue ordering",
                            "candidate": "Detached chronological events — not authorized"},
        })
    assert source.model_dump_json() == source_json and prefix.model_dump_json() == prefix_json
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase-step", type=int, default=10)
    parser.add_argument("--viewer-bundle", type=Path, required=True)
    parser.add_argument("--chronological", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / ".development-artifacts"
    output = args.output.resolve()
    if not output.is_relative_to(root) or output.exists():
        parser.error("Output must be a new directory under .development-artifacts")
    if args.phase_step < 5 or 360 % args.phase_step:
        parser.error("Phase step must divide 360 and be at least 5 degrees")
    if shutil.disk_usage(root).free < 1024 ** 3:
        parser.error("At least 1 GiB free is required for the bounded audit")
    viewer = args.viewer_bundle.read_bytes()
    if len(viewer) > 8 * 1024 ** 2:
        parser.error("Viewer bundle exceeds 8 MiB")
    output.mkdir(parents=True)
    (output / "viewer.js").write_bytes(viewer)
    (output / "viewer.css").write_bytes(args.viewer_bundle.with_suffix(".css").read_bytes())
    summaries, total_bytes = [], 0
    for phase in range(0, 360, args.phase_step):
        for direction in ("FORWARD", "REVERSE"):
            for prior in (False, True):
                case = build_case(phase, direction, prior_pose=prior, chronological=args.chronological)
                name = f"phase-{phase:03d}-{direction.lower()}-{'N' if prior else 'control'}.json"
                text = json.dumps(case, separators=(",", ":"), allow_nan=False)
                total_bytes += 2 * len(text.encode())
                if total_bytes > 512 * 1024 ** 2:
                    raise ValueError("Audit exceeded its 512 MiB evidence cap")
                (output / name).write_text(text)
                title = f"{phase}° · {direction} · {'prior N' if prior else 'commuting control'}"
                safe_json = text.replace("<", "\\u003c")
                (output / name.replace(".json", ".html")).write_text(
                    '<!doctype html><meta charset="utf-8">'
                    '<link rel="stylesheet" href="viewer.css">'
                    f'<title>Motion ordering: {escape(title)}</title>'
                    '<style>body{background:#0d1117;color:#ddd;font:14px sans-serif;margin:18px}'
                    'a{color:#79c0ff}table{border-collapse:collapse}td,th{padding:5px;border:1px solid #444}'
                    '#audit-status{position:fixed;bottom:2px;z-index:99999;background:#111}</style>'
                    f'<a href="index.html">All phases</a><h1>{escape(title)}</h1>'
                    '<p>Isolated ordering probe. No production authorization or complete member-motion semantics.</p>'
                    '<button id="open-audit">Open comparison</button><div id="junctions"></div>'
                    f'<script>window.MOTION_AUDIT={safe_json}</script><script src="viewer.js"></script>')
                summaries.append({"file": name, **case["case"], "displacement": {
                    k: v for k, v in case["displacement"].items() if k != "vectors"},
                    "current": case["current"]["diagnostics"],
                    "candidate": case["candidate"]["diagnostics"]})
        print(f"Recorded phase {phase} degrees", flush=True)
    (output / "index.json").write_text(json.dumps({
        "scope": "Isolated ordering probe only; not complete member-motion authorization evidence",
        "phase_step_deg": args.phase_step, "chronological": args.chronological,
        "cases": summaries}, separators=(",", ":"), allow_nan=False))
    rows = []
    for row in summaries:
        current, candidate = row["current"], row["candidate"]
        rows.append(f'<tr><td><a href="{row["file"].replace(".json", ".html")}">'
                    f'{row["phase_deg"]}° {row["direction"]} {"N" if row["prior_pose"] else "control"}</a></td>'
                    f'<td>{row["displacement"]["max_nm"]:.6f}</td>'
                    f'<td>{current["piercing"]["n_pierced"]} → {candidate["piercing"]["n_pierced"]}</td>'
                    f'<td>{current["n_clashes"]} → {candidate["n_clashes"]}</td>'
                    f'<td>{current["bonds"]["max_length_nm"]} → {candidate["bonds"]["max_length_nm"]}</td></tr>')
    (output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Isolated member-motion ordering review</title>'
        '<style>body{font:16px sans-serif;background:#0d1117;color:#ddd;margin:30px}'
        'a{color:#79c0ff}td,th{padding:8px;border-bottom:1px solid #444}</style>'
        '<h1>Isolated member-motion ordering review</h1>'
        '<p>Current native owner placement versus motion of exact native prefix material. '
        + ('The chronological variant applies the existing native residue translation D after diagnostic M, '
           'with an inspectable event trace. ' if args.chronological else '') +
        'No production placement is changed. Both helix directions are selected; the second helix is an exact control. '
        'Tails, partial helices, material birth, overlaps and later edit semantics are outside this probe. '
        'Phase variations are direct native fixture inputs, not cold-replayed history claims. '
        'Clash hits and overstretched-bond listings use the existing 200-row diagnostic caps; local counts '
        'refer to reported hits and may not be exhaustive.</p>'
        f'<p>Full 0–360° sampled phase coverage, step {args.phase_step}°. Each phase has both prior-residue '
        'directions and no-prior-pose controls. Each case opens Current, Candidate, Difference and Defects '
        'with Full and Ball and Stick. Coordinates remain in one shared world frame.</p>'
        '<table><tr><th>Case</th><th>Max displacement nm</th><th>Piercings</th>'
        '<th>Clashes</th><th>Max bond nm</th></tr>' + "".join(rows) + '</table>')
    print(f"Audit evidence: {output} ({total_bytes} bytes)", flush=True)


if __name__ == "__main__":
    main()
