"""Offline attached-Sweep ownership audit; never consumed by production."""

import json
from pathlib import Path
from uuid import UUID
import numpy as np
from backend.core.atomistic import build_atomistic_model, atomistic_to_json
from backend.core.deformation import deformed_helix_axes
from backend.core.molecular_placement_audit import (
    _model_diagnostics,
    _affected_serials,
    _defect_serials,
)
from tools.member_motion_audit import _junction_rows, roll_native_source
import shutil
from backend.core.base_keys import atom_base_key
from backend.core.models import (
    Direction,
    DomainRef,
)
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.sweep import SweepRequest, sweep_source
from backend.core.design_geometry import _geometry_for_design
from tests.test_part_member_motion_order import _source, _owner, _rigid, M
from tests.test_part_transform_preview import snapshot


def preserved_existing_owner_candidate(before, after):
    """Detached diagnosis only: exact surviving domains, no split/merge inference."""

    def signature(dom):
        return dom.helix_id, dom.start_bp, dom.end_bp, dom.direction

    old_domains = {
        signature(dom) for strand in before.strands for dom in strand.domains
    }
    new_refs = {}
    for strand in after.strands:
        for index, dom in enumerate(strand.domains):
            key = signature(dom)
            assert key not in new_refs, "Ambiguous domain identity; diagnostic refuses"
            new_refs[key] = DomainRef(strand_id=strand.id, domain_index=index)
    assert old_domains <= new_refs.keys(), (
        "Diagnostic does not infer split/merged ancestry"
    )
    old_owners = {c.id: c for c in before.cluster_transforms}
    clusters = []
    for owner in after.cluster_transforms:
        old = old_owners.get(owner.id)
        if old is None or not old.domain_ids:
            clusters.append(owner)
            continue
        preserved = [
            new_refs[
                signature(before.find_strand(ref.strand_id).domains[ref.domain_index])
            ]
            for ref in old.domain_ids
        ]
        born = [
            ref
            for ref in owner.domain_ids
            if signature(after.find_strand(ref.strand_id).domains[ref.domain_index])
            not in old_domains
        ]
        clusters.append(owner.model_copy(update={"domain_ids": preserved + born}))
    return after.copy_with(cluster_transforms=clusters)


def phase_source(phase_deg):
    source = _source()
    return roll_native_source(source, source.helices[0].id, phase_deg)


def build_case(phase_deg=0, direction="FORWARD", end="end"):
    direction = Direction(direction)
    source = phase_source(phase_deg)
    hid = source.helices[0].id
    source = snapshot(
        source,
        "nick",
        {"helix_id": hid, "bp_index": 3, "direction": direction.value},
        "nick",
    )
    bp = 0 if end == "start" else 7
    member = next(
        r
        for r in _geometry_for_design(source)
        if r["helix_id"] == hid
        and r["bp_index"] == bp
        and r["direction"] == direction.value
    )
    posed = _owner(source, source.find_strand(member["strand_id"]))
    body = SweepRequest(
        sweep_id=UUID(int=29001),
        cells=[(0, 0)],
        points_nm=[(0, 0, 0), (0, 0, (-1 if end == "start" else 1) * 7 * RISE)],
        source_helix_id=hid,
        source_end=end,
        ligate_adjacent=False,
    )
    before_json, posed_json = source.model_dump_json(), posed.model_dump_json()
    control = snapshot(source, "sweep", body.model_dump(mode="json"), "birth")
    repeated = snapshot(source, "sweep", body.model_dump(mode="json"), "birth")
    after = snapshot(posed, "sweep", body.model_dump(mode="json"), "birth")
    control_rows = _geometry_for_design(control)
    assert control_rows == _geometry_for_design(repeated)
    old_ids = {h.id for h in source.helices}
    new_ids = {h.id for h in after.helices} - old_ids
    actual = _geometry_for_design(after)
    a = np.asarray(
        [r["backbone_position"] for r in control_rows if r["helix_id"] in new_ids]
    )
    b = np.asarray([r["backbone_position"] for r in actual if r["helix_id"] in new_ids])
    old_rows = {
        (r["helix_id"], r["bp_index"], r["direction"], r.get("copy_k", 0)): r
        for r in _geometry_for_design(posed)
    }
    old_full_delta = [
        np.linalg.norm(
            np.asarray(r["backbone_position"])
            - old_rows[
                (r["helix_id"], r["bp_index"], r["direction"], r.get("copy_k", 0))
            ]["backbone_position"]
        )
        for r in actual
        if r["helix_id"] in old_ids
    ]
    candidate = preserved_existing_owner_candidate(posed, after)
    candidate_rows = _geometry_for_design(candidate)
    for row in candidate_rows:
        if row["helix_id"] not in old_ids:
            continue
        original = old_rows[
            (row["helix_id"], row["bp_index"], row["direction"], row.get("copy_k", 0))
        ]
        for field in (
            "backbone_position",
            "base_position",
            "slab_position",
            "base_normal",
            "axis_tangent",
            "slab_quaternion",
            "helical_site",
        ):
            assert row[field] == original[field], f"Existing Full {field} changed"

    candidate_full_delta = [
        np.linalg.norm(
            np.asarray(r["backbone_position"])
            - old_rows[
                (r["helix_id"], r["bp_index"], r["direction"], r.get("copy_k", 0))
            ]["backbone_position"]
        )
        for r in candidate_rows
        if r["helix_id"] in old_ids
    ]
    prior_atoms, control_atoms, actual_atoms = [
        build_atomistic_model(d, fast_bridges=True) for d in (posed, control, after)
    ]
    atom_key = lambda t: (atom_base_key(t), t.name)
    xyz = lambda t: np.asarray([t.x, t.y, t.z])
    prior_by_key = {atom_key(t): t for t in prior_atoms.atoms}
    old_atom_delta = [
        np.linalg.norm(xyz(t) - xyz(prior_by_key[atom_key(t)]))
        for t in actual_atoms.atoms
        if t.helix_id in old_ids
    ]
    candidate_atoms = build_atomistic_model(candidate, fast_bridges=True)
    candidate_old_atom_delta = [
        np.linalg.norm(xyz(t) - xyz(prior_by_key[atom_key(t)]))
        for t in candidate_atoms.atoms
        if t.helix_id in old_ids
    ]
    actual_by_key = {atom_key(t): t for t in actual_atoms.atoms}
    candidate_born_delta = [
        np.linalg.norm(xyz(t) - xyz(actual_by_key[atom_key(t)]))
        for t in candidate_atoms.atoms
        if t.helix_id in new_ids
    ]
    assert max(candidate_full_delta) < 1e-12 and max(candidate_old_atom_delta) < 1e-12
    assert max(candidate_born_delta) < 1e-12
    assert candidate_atoms.bonds == actual_atoms.bonds
    diagnostics = [
        _model_diagnostics(after, model) for model in (actual_atoms, candidate_atoms)
    ]
    affected, displacement = _affected_serials(
        actual_atoms, candidate_atoms, *diagnostics
    )
    junctions = _junction_rows(actual_atoms, candidate_atoms, diagnostics)
    audit = {
        "schema": "nadoc.member-motion-ordering-audit.v1",
        "read_only": True,
        "case": {"direction": direction.value, "end": end, "phase_deg": phase_deg},
        "provider": {
            "id": "detached-preserve-existing-owner",
            "label": "Preserve existing ownership",
            "not_authorized_for_production": True,
            "description": "Only exact surviving domain ownership restored; native new material retained. No split/merge inference or shared-frame decision.",
            "panel_labels": {
                "current": "Current: native Sweep",
                "candidate": "Candidate: preserve existing owners",
            },
            "panel_notes": {
                "current": "Native attached Sweep after partial placement",
                "candidate": "Existing domains restored; new geometry unchanged — not authorized",
            },
        },
        "current_design": after.model_dump(mode="json"),
        "candidate_design": after.model_dump(mode="json"),
        "nucleotides": actual,
        "helix_axes": deformed_helix_axes(after),
        "current": {
            **atomistic_to_json(actual_atoms),
            "diagnostics": diagnostics[0],
            "nucleotides": actual,
            "helix_axes": deformed_helix_axes(after),
        },
        "candidate": {
            **atomistic_to_json(candidate_atoms),
            "diagnostics": diagnostics[1],
            "nucleotides": candidate_rows,
            "helix_axes": deformed_helix_axes(candidate),
        },
        "affected_atom_serials": affected,
        "displacement": displacement,
        "defect_atom_serials": {
            side: _defect_serials(diag)
            for side, diag in zip(("current", "candidate"), diagnostics)
        },
        "junctions": junctions,
        "diagnostic_limits": {"clash_hit_cap": 200, "overstretched_bond_row_cap": 200},
        "invariants": {
            "old_full_restored": True,
            "old_atoms_restored": True,
            "new_atoms_unchanged": True,
            "bonds_unchanged": True,
        },
    }
    for junction in junctions:
        junction["birth_boundary"] = any(
            actual_atoms.atoms[i].helix_id in old_ids for i in junction["serials"]
        ) and any(
            actual_atoms.atoms[i].helix_id in new_ids for i in junction["serials"]
        )
        junction["material_keys"] = [
            atom_base_key(actual_atoms.atoms[i]) for i in junction["serials"]
        ]
    ca = {atom_key(t): t for t in control_atoms.atoms if t.helix_id in new_ids}
    born_atoms = [t for t in actual_atoms.atoms if t.helix_id in new_ids]
    atom_a = np.asarray([xyz(ca[atom_key(t)]) for t in born_atoms])
    atom_b = np.asarray([xyz(t) for t in born_atoms])
    native = sweep_source(posed, body)
    plain = sweep_source(source, body)
    parent = {
        r["direction"]: r["helical_site"]["axis_point"]
        for r in _geometry_for_design(posed)
        if r["helix_id"] == hid and r["bp_index"] == bp
    }
    summary = {
        "direction": direction.value,
        "end": end,
        "candidate_old_full_max_nm": float(max(candidate_full_delta)),
        "candidate_old_atom_max_nm": float(max(candidate_old_atom_delta)),
        "candidate_born_atom_change_nm": float(max(candidate_born_delta)),
        "candidate_bonds_unchanged": True,
        "new_residues": len(b),
        "new_atoms": len(born_atoms),
        "old_full_max_displacement_nm": float(max(old_full_delta)),
        "old_atom_max_displacement_nm": float(max(old_atom_delta)),
        "born_atoms_max_from_original_nm": float(
            np.max(np.linalg.norm(atom_b - atom_a, axis=1))
        ),
        "born_atoms_max_from_moved_nm": float(
            np.max(np.linalg.norm(atom_b - _rigid(atom_a, M), axis=1))
        ),
        "ancestry": {
            "native_feature_id": "birth",
            "producer": "sweep",
            "source_helix_id": hid,
            "source_end": end,
            "explicit_source_strand": False,
            "new_helix_ids": sorted(new_ids),
        },
        "cross_old_new_max_bond_nm": max(
            (
                float(
                    np.linalg.norm(
                        xyz(actual_atoms.atoms[i]) - xyz(actual_atoms.atoms[j])
                    )
                )
                for i, j in actual_atoms.bonds
                if (actual_atoms.atoms[i].helix_id in old_ids)
                != (actual_atoms.atoms[j].helix_id in old_ids)
            ),
            default=0,
        ),
        "cross_old_new_atom_bonds": sum(
            (actual_atoms.atoms[i].helix_id in old_ids)
            != (actual_atoms.atoms[j].helix_id in old_ids)
            for i, j in actual_atoms.bonds
        ),
        "parent_axis_points": parent,
        "native_source_origin": native["origin"].tolist(),
        "unposed_source_origin": plain["origin"].tolist(),
        "born_max_from_unposed_nm": float(np.max(np.linalg.norm(b - a, axis=1))),
        "born_max_from_moved_nm": float(
            np.max(np.linalg.norm(b - _rigid(a, M), axis=1))
        ),
        "control_exact": True,
        "scope": "Native source roll then partial owner and Sweep; not birth authorization",
    }
    assert (
        source.model_dump_json() == before_json
        and posed.model_dump_json() == posed_json
    )
    summary.update(
        phase_deg=phase_deg,
        birth_junctions=[j for j in junctions if j["birth_boundary"]],
    )
    return audit, summary


def main():
    import argparse
    from html import escape

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase-step", type=int, default=10)
    args = parser.parse_args()
    root = Path(".development-artifacts").resolve()
    output = args.output.resolve()
    if not output.is_relative_to(root) or output.exists():
        parser.error("Use a new directory under .development-artifacts")
    if args.phase_step < 5 or 360 % args.phase_step:
        parser.error("Phase step must divide360 and be at least5 degrees")
    if shutil.disk_usage(root).free < 1024**3:
        parser.error("At least1GiB free required")
    output.mkdir()
    for suffix in ("js", "css"):
        shutil.copyfile(
            root / "feature-history-focus" / f"member-motion-viewer.{suffix}",
            output / f"viewer.{suffix}",
        )
    summaries = []
    links = []
    total_bytes = 0
    for phase in range(0, 360, args.phase_step):
        for direction in Direction:
            for end in ("start", "end"):
                audit, summary = build_case(phase, direction, end)
                name = f"phase-{phase:03d}-{direction.value.lower()}-{end}"
                payload = json.dumps(audit, separators=(",", ":"), allow_nan=False)
                total_bytes += 2 * len(payload.encode())
                if total_bytes > 512 * 1024**2:
                    raise ValueError("Audit output exceeds512MiB")
                (output / f"{name}.json").write_text(payload)
                safe = payload.replace("<", "\\u003c")
                (output / f"{name}.html").write_text(
                    '<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="viewer.css">'
                    + f'<h1>{escape(name)}</h1><p>Isolated ownership candidate; new geometry unchanged. Native source roll changes evaluated geometry; no placement authorization.</p><button id="open-audit">Open comparison</button><div id="junctions"></div>'
                    + f'<script>window.MOTION_AUDIT={safe}</script><script src="viewer.js"></script>'
                )
                summaries.append(summary)
                links.append(f'<li><a href="{name}.html">{name}</a></li>')
        print(f"Completed phase {phase}: {len(summaries)} cases", flush=True)
    (output / "summary.json").write_text(
        json.dumps(summaries, indent=2, allow_nan=False)
    )
    (output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><h1>Sweep ownership and construction-frame review</h1><p>Existing material preserved in isolated candidate; newly created geometry unchanged. Every case includes current/candidate/difference/defect views and per-junction metrics. No production authorization.</p><ul>'
        + "".join(links)
        + "</ul>"
    )
    print(
        f"Completed {len(summaries)} cases; audit payload {total_bytes} bytes",
        flush=True,
    )


if __name__ == "__main__":
    main()
