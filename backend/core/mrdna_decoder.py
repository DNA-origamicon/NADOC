"""Identity-driven mrDNA trajectory decoding and structural quality checks."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.core.mrdna_manifest import MrdnaNucleotideManifest


def _kabsch(mobile: np.ndarray, target: np.ndarray) -> np.ndarray:
    cm, ct = mobile.mean(0), target.mean(0)
    covariance = (mobile - cm).T @ (target - ct)
    u, _s, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T @ u.T
    return (mobile - cm) @ rotation.T + ct


def decode_mrdna_frame(
    job_dir: Path,
    psf_path: Path,
    dcd_path: Path,
    *,
    design=None,
    frame: int = -1,
) -> dict:
    """Decode a complete nucleotide frame exclusively through the job manifest."""
    import MDAnalysis as mda

    from backend.core.mrdna_bridge import _unwrapped_universe_positions

    manifest = MrdnaNucleotideManifest.load_required(job_dir)
    unresolved = [r.identity.key() for r in manifest.records if not r.particle_bindings]
    if unresolved:
        raise RuntimeError(
            f"mrDNA manifest has {len(unresolved)} nucleotide(s) without particle bindings"
        )

    init_pdb = psf_path.with_suffix(".pdb")
    initial_u = mda.Universe(str(psf_path), str(init_pdb))
    initial = initial_u.atoms.positions.astype(float)
    trajectory_u = mda.Universe(str(psf_path), str(dcd_path))
    trajectory_u.trajectory[frame]
    simulated = _unwrapped_universe_positions(trajectory_u, initial).astype(float)
    if len(initial) != len(simulated):
        raise RuntimeError("mrDNA PSF/PDB/DCD particle counts disagree")
    aligned_nm = _kabsch(simulated, initial) / 10.0

    reference_by_key = {}
    if design is not None:
        from backend.core.design_geometry import _geometry_for_helices

        reference_by_key = {
            (
                p["helix_id"], p["bp_index"], p["direction"], p.get("copy", 0)
            ): p
            for p in _geometry_for_helices(design, None, junction_balance=True)
        }

    positions: list[dict] = []
    by_identity: dict[str, dict] = {}
    for record in manifest.records:
        indices = [binding.particle_index for binding in record.particle_bindings]
        if any(index >= len(aligned_nm) for index in indices):
            raise RuntimeError(
                f"mrDNA manifest particle index exceeds trajectory: {max(indices)} >= {len(aligned_nm)}"
            )
        point = sum(
            aligned_nm[binding.particle_index] * binding.weight
            for binding in record.particle_bindings
        )
        render_tuple = (
            record.render.helix_id,
            record.render.bp_index,
            record.render.direction,
            record.render.copy,
        )
        reference = reference_by_key.get(render_tuple)
        # DNA particles are helix-axis sites. Restore the nucleotide's radial
        # offset from the authoritative snapshot geometry; identity and particle
        # ownership still come solely from the manifest. NAS particles already
        # represent ssDNA contour positions and receive no duplex offset.
        if reference is not None and all(
            binding.particle_kind == "DNA" for binding in record.particle_bindings
        ):
            mate_direction = (
                "REVERSE" if record.render.direction == "FORWARD" else "FORWARD"
            )
            mate = reference_by_key.get(
                (
                    record.render.helix_id,
                    record.render.bp_index,
                    mate_direction,
                    record.render.copy,
                )
            )
            if mate is not None:
                axis = 0.5 * (
                    np.asarray(reference["backbone_position"])
                    + np.asarray(mate["backbone_position"])
                )
                point = point + (np.asarray(reference["backbone_position"]) - axis)
        entry = {
            "identity": record.identity.key(),
            "helix_id": record.render.helix_id,
            "bp_index": record.render.bp_index,
            "direction": record.render.direction,
            "copy": record.render.copy,
            "backbone_position": np.asarray(point).tolist(),
            "simulation_mode": record.simulation_mode,
            "classification": record.classification,
        }
        positions.append(entry)
        by_identity[entry["identity"]] = entry

    _add_nucleotide_frames(manifest, by_identity)

    quality = validate_decoded_frame(manifest, by_identity)
    return {
        "schema_version": manifest.schema_version,
        "positions": positions,
        "quality": quality,
        "confidence": {
            "direct": sum(p["simulation_mode"] == "direct" for p in positions),
            "interpolated": sum(
                p["simulation_mode"] == "interpolated" for p in positions
            ),
        },
    }


def _add_nucleotide_frames(
    manifest: MrdnaNucleotideManifest, by_identity: dict[str, dict]
) -> None:
    """Derive paired normals and local strand tangents from one decoded frame."""
    for record in manifest.records:
        ident = record.identity.key()
        entry = by_identity.get(ident)
        if entry is None:
            continue
        here = np.asarray(entry["backbone_position"])
        if record.pair in by_identity:
            normal = np.asarray(by_identity[record.pair]["backbone_position"]) - here
            norm = float(np.linalg.norm(normal))
            if norm > 1e-9:
                normal /= norm
                entry.update(nx=float(normal[0]), ny=float(normal[1]), nz=float(normal[2]))
        neighbors = [
            by_identity[target]
            for target in (record.predecessor, record.successor)
            if target in by_identity
            and by_identity[target]["helix_id"] == entry["helix_id"]
        ]
        if len(neighbors) == 2:
            tangent = np.asarray(neighbors[1]["backbone_position"]) - np.asarray(
                neighbors[0]["backbone_position"]
            )
        elif neighbors:
            tangent = np.asarray(neighbors[0]["backbone_position"]) - here
        else:
            continue
        norm = float(np.linalg.norm(tangent))
        if norm > 1e-9:
            tangent /= norm
            entry.update(tx=float(tangent[0]), ty=float(tangent[1]), tz=float(tangent[2]))


def validate_decoded_frame(
    manifest: MrdnaNucleotideManifest, by_identity: dict[str, dict]
) -> dict:
    """Validate coverage and covalent continuity for one complete frame."""
    bonds: list[dict] = []
    missing: list[str] = []
    records_by_identity = {
        record.identity.key(): record for record in manifest.records
    }
    for record in manifest.records:
        ident = record.identity.key()
        if ident not in by_identity:
            missing.append(ident)
            continue
        if record.successor is None or record.successor not in by_identity:
            continue
        a = np.asarray(by_identity[ident]["backbone_position"])
        b = np.asarray(by_identity[record.successor]["backbone_position"])
        length = float(np.linalg.norm(b - a))
        target_record = records_by_identity[record.successor]
        same_segment = (
            record.identity.strand_id == target_record.identity.strand_id
            and record.identity.segment_kind == target_record.identity.segment_kind
            and record.identity.segment_id == target_record.identity.segment_id
        )
        # mrDNA's DNA sites are helix-axis particles, not phosphates. Across a
        # crossover, adjacent strand nucleotides therefore land on different helix
        # axes and their displayed distance can legitimately approach the bundle's
        # inter-axis spacing. Treat those junction lengths as confidence warnings;
        # they still remain fully reported. A 1-bp Fine trajectory can transiently
        # put an axis-derived internal display bond just above 2 nm in early saved
        # frames; that is diagnostic, but must not erase the whole RMSF ensemble.
        # Only genuinely design-spanning (>5 nm) bonds make a frame unusable.
        severity = (
            "error"
            if length > 5.0
            else "warning"
            if length > 1.2
            else "ok"
        )
        bonds.append(
            {
                "from": ident,
                "to": record.successor,
                "length_nm": length,
                "junction": not same_segment,
                "severity": severity,
            }
        )
    errors = [bond for bond in bonds if bond["severity"] == "error"]
    warnings = [bond for bond in bonds if bond["severity"] == "warning"]
    return {
        "complete": not missing,
        "n_positions": len(by_identity),
        "n_expected": len(manifest.records),
        "missing_identities": missing,
        "n_bonds": len(bonds),
        "max_bond_nm": max((bond["length_nm"] for bond in bonds), default=0.0),
        "bond_errors": errors,
        "bond_warnings": warnings,
        "usable": not missing and not errors,
    }


def mrdna_backbone_strain_profile(
    manifest: MrdnaNucleotideManifest,
    positions: list[dict],
    reference_positions: list[dict],
) -> dict:
    """Signed local backbone strain from the same manifest identity graph.

    This is a geometric coarse-grained estimate, not an atomistic force/energy:
    each covalent edge is compared with that exact edge in the job snapshot and
    its fractional length change is assigned to both incident nucleotides.  The
    largest-magnitude incident value is shown at junctions so extension and
    compression do not cancel visually.
    """
    current_by_identity = {p.get("identity"): p for p in positions}
    reference_by_render = {
        (
            p["helix_id"], p["bp_index"],
            getattr(p["direction"], "value", p["direction"]), int(p.get("copy", 0)),
        ): np.asarray(p["backbone_position"], dtype=float)
        for p in reference_positions
    }
    record_by_identity = {r.identity.key(): r for r in manifest.records}
    incident: dict[str, list[float]] = {identity: [] for identity in record_by_identity}
    n_edges = 0
    for identity, record in record_by_identity.items():
        successor = record.successor
        if successor is None or identity not in current_by_identity or successor not in current_by_identity:
            continue
        other = record_by_identity[successor]
        ref_a = reference_by_render.get((
            record.render.helix_id, record.render.bp_index, record.render.direction,
            record.render.copy,
        ))
        ref_b = reference_by_render.get((
            other.render.helix_id, other.render.bp_index, other.render.direction,
            other.render.copy,
        ))
        if ref_a is None or ref_b is None:
            continue
        rest = float(np.linalg.norm(ref_b - ref_a))
        if rest <= 1e-9:
            continue
        cur_a = np.asarray(current_by_identity[identity]["backbone_position"], dtype=float)
        cur_b = np.asarray(current_by_identity[successor]["backbone_position"], dtype=float)
        value = float(np.linalg.norm(cur_b - cur_a) / rest - 1.0)
        incident[identity].append(value)
        incident[successor].append(value)
        n_edges += 1

    output = []
    measured = []
    for position in positions:
        values = incident.get(position.get("identity"), [])
        strain = max(values, key=abs) if values else None
        entry = {**position, "strain": strain}
        record = record_by_identity.get(position.get("identity"))
        entry["ss"] = record is None or record.classification != "duplex"
        output.append(entry)
        if strain is not None:
            measured.append(strain)
    absolute = np.abs(np.asarray(measured, dtype=float))
    robust = float(np.quantile(absolute, 0.95)) if len(absolute) else 0.0
    return {
        "positions": output,
        "metric": "backbone_geometric",
        "n": len(measured),
        "n_edges": n_edges,
        "min_strain": min(measured, default=0.0),
        "max_strain": max(measured, default=0.0),
        "abs_max_strain": max((abs(v) for v in measured), default=0.0),
        "display_abs_strain": robust,
    }
