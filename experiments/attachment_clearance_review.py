"""Isolated evidence for retaining separate overhangs in attachment clearance.

This is not imported by the application. The candidate exists only inside a
restoring context manager in this diagnostic process; it cannot be selected by
ordinary display, export, persistence, or simulation controls.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import gzip
import json
from pathlib import Path
import sys

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def candidate_obstacles(geometry, version, root, proteins=(), *, host_only=False):
    """Keep other overhangs, including ones inside the root exemption radius."""
    host_strands = {n["strand_id"] for n in geometry if n.get("overhang_id") == version.overhang_id}
    points = np.asarray([
        n[key]
        for n in geometry
        if n.get("strand_id") != version.strand_id
        and n.get("overhang_id") != version.overhang_id
        for key in ("backbone_position", "base_position")
        if n.get("overhang_id") is not None
        or (host_only and n.get("strand_id") not in host_strands)
        or np.linalg.norm(np.asarray(n[key]) - root) > 2.0
    ], dtype=float).reshape((-1, 3))
    return cKDTree(np.concatenate([points, np.asarray(proteins).reshape((-1, 3))]))


def candidate_host_obstacles(geometry, version, root, proteins=()):
    """Limit the near-root covalent exemption to the overhang's host strand."""
    return candidate_obstacles(geometry, version, root, proteins, host_only=True)


@contextmanager
def diagnostic_candidate(provider=candidate_obstacles, fit_provider=None):
    from backend.api import nanoparticle_attachment

    original = nanoparticle_attachment.duplex_obstacles
    original_fit = nanoparticle_attachment.fit_swing
    nanoparticle_attachment.duplex_obstacles = provider
    if fit_provider is not None:
        nanoparticle_attachment.fit_swing = fit_provider
    try:
        yield
    finally:
        nanoparticle_attachment.duplex_obstacles = original
        nanoparticle_attachment.fit_swing = original_fit


def _failure_frames(error):
    frames = {}
    while error:
        tb = error.__traceback__
        while tb:
            frames[tb.tb_frame.f_code.co_name] = tb.tb_frame.f_locals
            tb = tb.tb_next
        error = error.__cause__
    return frames


def _landmark_pair(geometry, version, root, provider=None):
    from backend.core.nanoparticle_attachment_obstacles import duplex_obstacles

    rows = [(n, key) for n in geometry
            if n.get("strand_id") == version.strand_id
            or n.get("overhang_id") == version.overhang_id
            for key in ("backbone_position", "base_position")]
    tree = (provider or duplex_obstacles)(geometry, version, root)
    distances, indices = tree.query([n[key] for n, key in rows])
    index = int(np.argmin(distances))
    point = tree.data[indices[index]]
    other = min(((np.linalg.norm(np.asarray(n[key])-point), n, key)
                 for n in geometry for key in ("backbone_position", "base_position")),
                key=lambda row: row[0])
    return {"distance_nm": float(distances[index]), "rows": [rows[index], other[1:]]}


def _crop_model(model, indices):
    from backend.core.atomistic import AtomisticModel

    remap = {old: new for new, old in enumerate(indices)}
    return AtomisticModel(
        [replace(model.atoms[old], serial=new) for old, new in remap.items()],
        [(remap[a], remap[b]) for a, b in model.bonds if a in remap and b in remap],
        model.warnings,
    )


def enrich_summary(bundle):
    """Per-junction display measurements from the exported native atom feeds."""
    sides = ("current", "candidate")
    xyz = {s: np.array([[a[k] for k in ("x", "y", "z")] for a in bundle[s]["atoms"]])
           for s in sides}
    delta = np.linalg.norm(xyz["candidate"] - xyz["current"], axis=1)
    site = lambda a: (a["strand_id"], a["helix_id"], a["bp_index"], a["direction"])
    versions = bundle["current_design"]["nanoparticle_connection_versions"]
    for row in bundle["summary"]["joints"]:
        version = next(v for v in versions if v["overhang_id"] == row["overhang_id"] and v["applied"])
        sites = {site(n) for n in bundle["current"]["nucleotides"]
                 if n.get("strand_id") == version["strand_id"] or n.get("overhang_id") == row["overhang_id"]}
        owned = {i for i, a in enumerate(bundle["current"]["atoms"]) if site(a) in sites}
        if not owned:
            continue  # Unchanged junction outside this comparison's atom crop.
        row["max_atom_displacement_nm"] = float(delta[list(owned)].max())
        row["rms_atom_displacement_nm"] = float(np.sqrt(np.mean(delta[list(owned)]**2)))
        for s in sides:
            data = bundle[s]
            bonds = [(i, j) for i, j in data["bonds"] if i in owned or j in owned]
            row[s]["max_bond_nm"] = max(float(np.linalg.norm(xyz[s][i] - xyz[s][j])) for i, j in bonds)
            row[s]["clashes"] = sum(bool(owned.intersection(h["serials"])) for h in data["diagnostics"]["clashes"])
            row[s]["piercings"] = sum(bool(owned.intersection(h["bond_serials"] + h["ring_serials"]))
                                      for h in data["diagnostics"]["piercing"]["pierced"])
    pairs = {s: {tuple(sorted(h["serials"])) for h in bundle[s]["diagnostics"]["bonds"]["overstretched"]}
             for s in sides}
    bundle["summary"]["overstretched_pair_changes"] = {
        "introduced": sorted(pairs["candidate"] - pairs["current"]),
        "removed": sorted(pairs["current"] - pairs["candidate"]),
    }


def phase_controls(provider=candidate_obstacles, fit_provider=None):
    """Unchanged 2HB positive/negative controls over a complete helical turn."""
    import hashlib
    from backend.core.atomistic import build_atomistic_model, atomistic_to_json
    from backend.core.design_geometry import fitting_geometry
    from backend.core.molecular_placement_audit import _model_diagnostics, _defect_serials
    from tests.reciprocal_design import reciprocal_design

    rows, examples = [], {}
    for extra in ("T", "TT"):
        for bp in range(8, 19):
            design = reciprocal_design(extra, bp=bp)
            current = build_atomistic_model(design)
            with diagnostic_candidate(provider, fit_provider):
                candidate = build_atomistic_model(design)
            payload = lambda model: json.dumps(atomistic_to_json(model), sort_keys=True).encode()
            current_hash = hashlib.sha256(payload(current)).hexdigest()
            candidate_hash = hashlib.sha256(payload(candidate)).hexdigest()
            assert current_hash == candidate_hash
            diagnostics = _model_diagnostics(design, current)
            verdict = "pierced" if diagnostics["piercing"]["n_pierced"] else "clear"
            rows.append({"extra_bases": extra, "bp": bp, "atom_hash": current_hash,
                         "candidate_identical": True, "piercings": diagnostics["piercing"]["n_pierced"],
                         "clashes": diagnostics["n_clashes"]})
            if verdict not in examples:
                data = {**atomistic_to_json(current), "diagnostics": diagnostics,
                        "nucleotides": fitting_geometry(design)}
                examples[verdict] = {
                    "schema": "nadoc.attachment-clearance-control.v1", "read_only": True,
                    "provider": {"label": f"Unchanged 2HB control: {extra}, register {bp} ({verdict})"},
                    "current_design": design.model_dump(mode="json"),
                    "candidate_design": design.model_dump(mode="json"),
                    "current": data, "candidate": data,
                    "affected_atom_serials": [], "midpoint_constraint_planes": [],
                    "defect_atom_serials": {side: _defect_serials(diagnostics) for side in ("current", "candidate")},
                    "displacement": {"n_displaced": 0, "max_nm": 0, "rms_nm": 0, "vectors": []},
                    "feature_sequence": [],
                }
    assert set(examples) == {"clear", "pierced"}
    return rows, examples


def build_review(output, provider=candidate_obstacles, fit_provider=None):
    from backend.api import nanoparticle_attachment
    from backend.api.generated_history import build_recorded
    from backend.api.nanoparticle_attachment import attach_nanoparticle
    from backend.core.atomistic import build_atomistic_model, atomistic_to_json
    from backend.core.design_geometry import fitting_geometry
    from backend.core.molecular_placement_audit import (
        _model_diagnostics, _affected_serials, _defect_serials,
    )
    from backend.core.platform_generator import plan_generated
    from backend.core.two_np_generator import GeneratorSettings
    from backend.core.validator import validate_design
    from tests.test_curved_rod_generator import source

    output.mkdir(parents=True, exist_ok=True)
    original = source()
    original_json = original.model_dump_json()
    settings = GeneratorSettings(shape="platform", connections_per_particle=3)
    plan, _ = plan_generated(original, settings)
    print("Reproduce production refusal", flush=True)
    attachment_calls = []
    def trace_attachment(design, *args, **kwargs):
        attachment_calls.append((design, args, kwargs))
        return attach_nanoparticle(design, *args, **kwargs)
    nanoparticle_attachment.attach_nanoparticle = trace_attachment
    try:
        build_recorded(original, plan, settings)
    except ValueError as error:
        frames = _failure_frames(error)
        failed = frames["attach_nanoparticle"]
        prefix = frames["build_recorded"]["history"].design
        reason = str(error)
    else:
        raise AssertionError("Expected the recorded production refusal")
    finally:
        nanoparticle_attachment.attach_nanoparticle = attach_nanoparticle
    current, before = failed["out"], failed["design"]
    before_json = before.model_dump_json()
    version = failed["v"]
    args = {key: failed[key] for key in (
        "strand_id", "fixed_center", "frame", "angles", "place_new_graft", "pending_connections"
    )}
    print("Build isolated alternative from the same authored input", flush=True)
    with diagnostic_candidate(provider, fit_provider):
        if fit_provider is None:
            candidate, attachment = attach_nanoparticle(
                before, failed["nanoparticle_id"], failed["overhang_id"], **args,
            )
        else:
            assert len(attachment_calls) == 4
            candidate = attachment_calls[0][0]
            for _, call_args, call_kwargs in attachment_calls:
                candidate, attachment = attach_nanoparticle(candidate, *call_args, **call_kwargs)
    assert before.model_dump_json() == before_json
    assert original.model_dump_json() == original_json
    assert current.strands == candidate.strands
    assert current.crossovers == candidate.crossovers
    assert current.nanoparticles == candidate.nanoparticles
    geometry = {"current": fitting_geometry(current), "candidate": fitting_geometry(candidate)}
    pending = args["pending_connections"]
    pending_overhangs = {item["overhang_id"] for item in pending}
    pending_handles = {item["strand_id"] for item in pending}
    obstacles = {side: [n for n in rows if n.get("overhang_id") not in pending_overhangs
                       and n.get("strand_id") not in pending_handles] for side, rows in geometry.items()}
    pairs = {side: _landmark_pair(rows, version, failed["root"], provider if side == "candidate" else None)
             for side, rows in obstacles.items()}
    offending_rows = pairs["current"]["rows"]
    # Crop by complete residue identities in a common world-space neighborhood.
    # Atom generation itself always sees the complete, unmodified native design.
    center = np.mean([n[key] for n, key in offending_rows], axis=0)
    print("Build native atomistic models, then select an identical local crop", flush=True)
    models = {side: build_atomistic_model(design, fast_bridges=True)
              for side, design in (("current", current), ("candidate", candidate))}
    if fit_provider is not None:
        emitted = {(a.strand_id, a.name): np.array([a.x, a.y, a.z])
                   for a in models["candidate"].atoms}
        linker_errors = [float(np.linalg.norm(emitted[(strand, name)] - point))
                         for strand, atoms in fit_provider.predicted_linkers.items()
                         for name, point in atoms.items() if (strand, name) in emitted]
        assert len(linker_errors) == 4 * 8
        assert max(linker_errors) < 1e-6
        print(f"Native predicted/emitted linker discrepancy: {max(linker_errors):.3g} nm", flush=True)
    assert models["current"].bonds == models["candidate"].bonds
    atom_identity = lambda a: (a.strand_id, a.helix_id, a.bp_index, a.direction,
                               a.copy_k, a.crossover_id, a.extra_base_k, a.name)
    assert [atom_identity(a) for a in models["current"].atoms] == [atom_identity(a) for a in models["candidate"].atoms]
    residue = lambda a: (a.strand_id, a.helix_id, a.bp_index, a.direction, a.copy_k or 0)
    selected = {residue(a) for model in models.values() for a in model.atoms
                if np.linalg.norm(np.array([a.x, a.y, a.z])-center) < 8.0}
    indices = [i for i, a in enumerate(models["current"].atoms) if residue(a) in selected]
    entire_delta = np.linalg.norm(
        np.array([[a.x, a.y, a.z] for a in models["current"].atoms])
        - np.array([[a.x, a.y, a.z] for a in models["candidate"].atoms]), axis=1,
    )
    moved = set(np.flatnonzero(entire_delta > 1e-6).tolist())
    # Include every moved residue as well as the collision neighborhood.
    selected.update(residue(models["current"].atoms[i]) for i in moved)
    indices = [i for i, a in enumerate(models["current"].atoms) if residue(a) in selected]
    models = {side: _crop_model(model, indices) for side, model in models.items()}
    print(f"Audit {len(indices)} atoms, all changed atoms retained", flush=True)
    diagnostics = {side: _model_diagnostics(design, models[side])
                   for side, design in (("current", current), ("candidate", candidate))}
    affected, displacement = _affected_serials(
        models["current"], models["candidate"], diagnostics["current"], diagnostics["candidate"],
    )
    full_geometry = geometry
    geometry = {side: [n for n in rows if
                      (n["strand_id"], n["helix_id"], n["bp_index"], n["direction"], n.get("copy_k", 0)) in selected]
                for side, rows in geometry.items()}
    assert all(geometry.values()), "The Full crop must contain the same native residues as the atom crop"
    from backend.core.nanoparticle_attachment_fit import attachment_joint
    from backend.core.protein import resolve_overhang_anchor
    joints = []
    for i, old_version in enumerate(current.nanoparticle_connection_versions):
        if not old_version.applied:
            continue
        row = {"connection": i+1, "overhang_id": old_version.overhang_id}
        for side, design in (("current", current), ("candidate", candidate)):
            v = next(v for v in design.nanoparticle_connection_versions
                     if v.strand_id == old_version.strand_id and v.applied)
            joint, local = attachment_joint(design, v, full_geometry[side])
            particle = next(p for p in design.nanoparticles if p.id == v.nanoparticle_id)
            root, _ = resolve_overhang_anchor(full_geometry[side], v.overhang_id, "root")
            row[side] = {
                "residual_nm": float(np.linalg.norm(joint-(particle.pose.to_array() @ np.r_[local, 1])[:3])),
                "minimum_landmark_distance_nm": _landmark_pair(obstacles[side], v, root,
                    provider if side == "candidate" else None)["distance_nm"],
            }
        joints.append(row)
    print("Confirm complete nine-attachment construction in the isolated candidate", flush=True)
    with diagnostic_candidate(provider, fit_provider):
        completed, report = build_recorded(original, plan, settings)
    assert validate_design(completed).passed
    assert len(report["connections"]) == 9
    for a, b in zip(original.nanoparticles, completed.nanoparticles):
        np.testing.assert_array_equal(a.pose.to_array()[:3, 3], b.pose.to_array()[:3, 3])
    summary = {
        "current_refusal": reason, "candidate_connections": len(report["connections"]),
        "candidate_max_residual_nm": max(report["attachment_residuals_nm"]),
        "fixed_centers_unchanged": True, "native_atom_and_bond_identity_equal": True,
        "comparison_scope": "four_attachments_from_same_unbound_input" if fit_provider else "rejected_step_only",
        "linker_prediction_max_error_nm": max(linker_errors) if fit_provider else None,
        "local_crop_atoms": len(indices), "all_moved_atoms_in_crop": moved.issubset(indices),
        "current_distance_nm": pairs["current"]["distance_nm"],
        "candidate_distance_nm": pairs["candidate"]["distance_nm"],
        "joints": joints,
        "diagnostics": {side: {"clashes": d["n_clashes"], "piercings": d["piercing"]["n_pierced"],
                                "bonds": d["bonds"]} for side, d in diagnostics.items()},
        "displacement": {k: v for k, v in displacement.items() if k != "vectors"},
    }
    clash_pairs = {side: {tuple(sorted(hit["serials"])) for hit in diag["clashes"]}
                   for side, diag in diagnostics.items()}
    summary["clash_pair_changes"] = {
        "introduced": sorted(clash_pairs["candidate"] - clash_pairs["current"]),
        "removed": sorted(clash_pairs["current"] - clash_pairs["candidate"]),
    }
    design_rows = {side: design.model_dump(mode="json", exclude={"feature_log", "loadouts"})
                   for side, design in (("current", current), ("candidate", candidate))}
    print("Verify unchanged 2HB molecular controls across the full helical phase sweep", flush=True)
    phase_rows, controls = phase_controls(provider, fit_provider)
    summary["phase_controls"] = phase_rows
    bundle = {
        "schema": "nadoc.attachment-clearance-review.v1", "read_only": True,
        "provider": {"id": provider.__name__, "label": (
            "Root exemption restricted to its covalent host strand (isolated candidate)"
            if provider is candidate_host_obstacles else "Separate overhangs remain obstacles (isolated candidate)"
        ), "fit_policy": fit_provider.__name__ if fit_provider else "maximum_landmark_clearance"},
        **{f"{side}_design": d for side, d in design_rows.items()},
        **{side: {**atomistic_to_json(models[side]), "diagnostics": diagnostics[side],
                  "nucleotides": geometry[side]} for side in models},
        "affected_atom_serials": affected,
        "defect_atom_serials": {side: _defect_serials(d) for side, d in diagnostics.items()},
        "midpoint_constraint_planes": [], "displacement": displacement,
        "landmark_pairs": pairs, "summary": summary,
        "pending_connections": pending,
        "feature_sequence": [{"index": i+1, "kind": getattr(e, "op_kind", e.feature_type),
                              "label": getattr(e, "label", "")}
                             for i, e in enumerate(prefix.feature_log)],
        "crop": {"center_nm": center.tolist(), "radius_nm": 8, "all_changed_atoms_included": True},
        "controls": controls,
    }
    enrich_summary(bundle)
    # Candidate is a read-only review feed. Only the accepted PRODUCTION prefix
    # is offered as a .nadoc document; the rejected and candidate drafts are not.
    (output / "production-prefix.nadoc").write_text(prefix.model_dump_json())
    with gzip.open(output / "comparison.json.gz", "wt") as stream:
        json.dump(bundle, stream, separators=(",", ":"))
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in {"joints", "diagnostics"}}), flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--candidate", choices=("host", "overhang", "host-bond"), default="host-bond")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--bundle", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.output is None:
        folder = {"host": "platform-host-clearance-review", "overhang": "platform-clearance-review",
                  "host-bond": "platform-bond-clearance-review"}[args.candidate]
        args.output = ROOT / ".development-artifacts/feature-history-focus" / folder
    if args.build:
        fit_provider = None
        if args.candidate == "host-bond":
            from experiments.attachment_bond_candidate import fit_shortest_root_bond
            fit_provider = fit_shortest_root_bond
        build_review(args.output, candidate_obstacles if args.candidate == "overhang" else candidate_host_obstacles,
                     fit_provider)
    if args.bundle:
        import shutil
        import subprocess

        if not (args.output / "comparison.json.gz").is_file():
            parser.error("Build the comparison first")
        subprocess.run([
            str(ROOT / "frontend/node_modules/.bin/esbuild"),
            str(ROOT / "experiments/attachment_clearance_review.js"),
            "--bundle", "--format=esm", "--minify",
            f"--outfile={args.output / 'review.js'}",
        ], check=True)
        shutil.copyfile(ROOT / "experiments/attachment_clearance_review.html", args.output / "index.html")
    if args.serve:
        from functools import partial
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import webbrowser

        for filename in ("index.html", "review.js", "comparison.json.gz"):
            if not (args.output / filename).is_file():
                parser.error(f"Missing review artifact: {filename}; run --build --bundle first")
        handler = partial(SimpleHTTPRequestHandler, directory=str(args.output.resolve()))
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            url = f"http://127.0.0.1:{server.server_port}/"
            print(f"Read-only attachment review: {url}\nCtrl-C stops the viewer server.", flush=True)
            if not args.no_open:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
