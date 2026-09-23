"""One design-specific loss inventory for export enforcement and the review dialog."""

from __future__ import annotations

import hashlib
import json

from backend.core.models import Design, Direction, LatticeType, StrandType
from backend.core.topology_integrity import (
    domain_order_errors,
    occupancy_errors,
    junction_errors,
)


def compatibility_report(design: Design, target: str) -> dict:
    if target not in ("cadnano", "scadnano"):
        raise ValueError("Unknown interchange format.")
    issues = []

    def add(code, label, count, effect, blocking=False):
        if count:
            issues.append(
                dict(
                    code=code,
                    label=label,
                    count=int(count),
                    effect=effect,
                    severity="error" if blocking else "warning",
                )
            )

    active = [s for s in design.strands if not s.is_reference]
    add(
        "reference_strands",
        "Reference strands",
        len(design.strands) - len(active),
        "Inactive reference strands are omitted from the exported file.",
    )
    add(
        "lattice",
        "Unsupported lattice",
        design.lattice_type not in (LatticeType.HONEYCOMB, LatticeType.SQUARE),
        "Only square and honeycomb lattices are supported.",
        True,
    )
    add(
        "empty_design",
        "Empty design",
        not design.helices or not active,
        "There is no supported strand topology to export.",
        True,
    )
    errors = (
        domain_order_errors(design) + occupancy_errors(design) + junction_errors(design)
    )
    if len({h.id for h in design.helices}) != len(design.helices):
        errors.append("Duplicate helix IDs.")
    if len({s.id for s in active}) != len(active):
        errors.append("Duplicate strand IDs.")
    add(
        "invalid_topology", "Invalid topology", len(errors), "; ".join(errors[:8]), True
    )
    missing = [
        dm
        for s in active
        for dm in s.domains
        if dm.helix_id not in {h.id for h in design.helices}
    ]
    add(
        "missing_helices",
        "Missing domain helices",
        len(missing),
        "Domain material cannot be encoded on a missing helix.",
        True,
    )
    from backend.core.sequences import strand_sequence_length

    add(
        "sequence_lengths",
        "Inconsistent sequence lengths",
        sum(
            s.sequence is not None
            and len(s.sequence) != strand_sequence_length(design, s)
            for s in active
        ),
        "Assigned sequences do not match the nucleotide inventory.",
        True,
    )
    junctions = [*design.crossovers, *design.forced_ligations]
    from backend.core.scaffold_safety import _has_backbone_edge
    from backend.core.topology_integrity import forced_edge, half_slot

    pending = sum(
        not _has_backbone_edge(design, forced_edge(f)) for f in design.forced_ligations
    )
    pending += sum(
        not (
            _has_backbone_edge(design, (half_slot(x.half_a), half_slot(x.half_b)))
            or _has_backbone_edge(design, (half_slot(x.half_b), half_slot(x.half_a)))
        )
        for x in design.crossovers
    )
    add(
        "pending_junctions",
        "Unrealized junction records",
        pending,
        "These records do not have a corresponding directed backbone connection; exporting would omit the intended bond.",
        True,
    )
    add(
        "junction_extra_bases",
        "Junction extra bases",
        sum(bool(j.extra_bases) for j in junctions),
        "This exporter cannot encode junction sequences faithfully. They are not duplex insertion columns. Save as .nadoc.",
        True,
    )
    add(
        "periodic_seams",
        "Periodic seams",
        sum(bool(f.is_periodic_seam) for f in design.forced_ligations),
        "Periodic seam intent has no supported representation in this export. Save as .nadoc.",
        True,
    )
    add(
        "forced_ligations",
        "Forced-ligation annotations",
        len(design.forced_ligations),
        "Ordered domain connectivity is encoded, but forced-ligation identity and annotations are not retained.",
    )
    add(
        "junction_annotations",
        "Crossover annotations",
        sum(bool(x.process_id) for x in design.crossovers),
        "Crossover operation labels and junction IDs are not retained.",
    )
    add(
        "extension_ownership",
        "Unresolved terminal extension ownership",
        sum(e.strand_id not in {s.id for s in active} for e in design.extensions),
        "An extension does not belong to an exported strand.",
        True,
    )
    add(
        "extension_labels",
        "Terminal extension labels",
        sum(bool(e.label) for e in design.extensions),
        "Extension labels are not retained.",
    )
    add(
        "scaffold_colors",
        "Scaffold color overrides",
        sum(bool(s.color) for s in active if s.is_scaffold),
        "Scaffold color overrides are not retained.",
    )
    add(
        "terminal_modifications",
        "Terminal chemical modifications",
        sum(bool(e.modification) for e in design.extensions),
        "Terminal chemical modifications cannot be encoded faithfully by this exporter.",
        True,
    )
    add(
        "special_strands",
        "Linker and overhang-binder strands",
        sum(
            s.strand_type not in (StrandType.SCAFFOLD, StrandType.STAPLE)
            for s in active
        ),
        "Synthetic/linker and binder identities cannot be represented as ordinary scaffold/staple lattice strands.",
        True,
    )
    add(
        "strand_annotations",
        "Strand names and notes",
        sum(bool(s.name or s.notes) for s in active),
        "Strand names and notes are not retained by this exporter.",
    )
    add(
        "domain_tags",
        "Overhang and binder domain tags",
        sum(
            bool(d.overhang_id or d.binds_overhang_id)
            for s in active
            for d in s.domains
        ),
        "Domains become ordinary lattice domains; attachment identities and overhang tags are lost.",
    )
    if target == "cadnano":
        add(
            "sequences",
            "Assigned strand sequences",
            sum(s.sequence is not None for s in active),
            "caDNAno v2 JSON does not store strand sequences. Export the sequence table separately.",
        )
        add(
            "extensions",
            "Terminal extension bases",
            sum(bool(e.sequence) for e in design.extensions),
            "caDNAno v2 export cannot retain terminal extension bases.",
            True,
        )
        add(
            "single_nucleotides",
            "Isolated one-position strands",
            sum(
                sum(abs(d.end_bp - d.start_bp) + 1 for d in s.domains) == 1
                for s in active
            ),
            "A one-position linear strand has the same pointer encoding as an empty caDNAno slot.",
            True,
        )
        add(
            "photoproduct_junctions",
            "Photoproduct junctions",
            len(design.photoproduct_junctions),
            "caDNAno cannot retain product-state chemistry.",
            True,
        )
        # caDNAno assigns one scaffold and one staple path per column by parity.
        from backend.core.cadnano import _export_layout

        if design.helices and not missing:
            layout = _export_layout(design.model_copy(update={"strands": active}))
            bad = 0
            for s in active:
                for d in s.domains:
                    expected = layout["export_dirs"][d.helix_id]
                    if not s.is_scaffold:
                        expected = (
                            Direction.REVERSE
                            if expected == Direction.FORWARD
                            else Direction.FORWARD
                        )
                    bad += d.direction != expected
            add(
                "direction_parity",
                "Noncanonical strand directions",
                bad,
                "caDNAno helix parity would reinterpret these strand directions.",
                True,
            )
            cells = list(zip(layout["rows"].values(), layout["cols"].values()))
            add(
                "grid_collisions",
                "Overlapping helix grid cells",
                len(cells) - len(set(cells)),
                "Distinct helices map to the same caDNAno grid cell.",
                True,
            )
            add(
                "coordinate_origin",
                "Negative nucleotide coordinates",
                layout["offset"] != 0,
                f"All nucleotide labels shift by +{layout['offset']} to fit caDNAno arrays; relative offsets are retained.",
            )
    else:
        add(
            "partial_sequences",
            "Partially assigned sequences",
            sum(
                s.sequence is None
                and any(e.strand_id == s.id and e.sequence for e in design.extensions)
                for s in active
            ),
            "Unassigned domain bases are written as N so assigned terminal extension sequences retain their positions.",
        )
        add(
            "photoproduct_junctions",
            "Photoproduct junctions (NADOC extension)",
            len(design.photoproduct_junctions),
            "Written in the CPD-fork extension; standard scadnano does not preserve this chemistry.",
        )
        add(
            "missing_grid",
            "Helices without lattice cells",
            sum(h.grid_pos is None for h in design.helices),
            "The scadnano lattice exporter cannot faithfully place these helices.",
            True,
        )
        cells = [h.grid_pos for h in design.helices if h.grid_pos is not None]
        add(
            "grid_collisions",
            "Overlapping helix grid cells",
            len(cells) - len(set(cells)),
            "Distinct helices occupy the same scadnano grid cell.",
            True,
        )
    add(
        "native_geometry",
        "Native residue coordinates",
        sum(bool(h.native_residues or h.native_source) for h in design.helices),
        "Native residue coordinates are replaced by ideal lattice geometry.",
    )
    # Every present NADOC-only design field gets a row. Adding a future field to
    # Design cannot silently bypass the loss inventory.
    handled = {
        "id",
        "helices",
        "strands",
        "lattice_type",
        "metadata",
        "extensions",
        "photoproduct_junctions",
        "crossovers",
        "forced_ligations",
        # Selection/cursor identifiers are implementation details of the
        # already-listed loadouts and history, not additional feature losses.
        "active_loadout_id",
        "last_editable_loadout_id",
        "feature_log_cursor",
        "feature_log_sub_cursor",
    }
    labels = {
        "cluster_transforms": "Cluster membership and transforms",
        "nucleotide_transforms": "Nucleotide transforms",
        "deformations": "Bends and twists",
        "overhang_connections": "Overhang connections",
        "overhang_bindings": "Overhang bindings",
    }
    defaults = Design().model_dump(mode="json")
    current = design.model_dump(mode="json")
    for field, value in current.items():
        if field in handled or value == defaults.get(field) or value is None:
            continue
        add(
            field,
            labels.get(field, field.replace("_", " ").capitalize()),
            len(value) if isinstance(value, (list, dict)) else 1,
            "Not retained in this format; the .nadoc file retains this information.",
        )
    # Saved scientific setup and design provenance also live under metadata.
    # Names are exported; file-identity bookkeeping is internal to NADOC.
    for field, value in current["metadata"].items():
        if (
            field in {"name", "identity_last_known_path", "identity_confirmed_at"}
            or value == defaults["metadata"].get(field)
            or value is None
        ):
            continue
        add(
            "metadata_" + field,
            "Design " + field.replace("_", " "),
            len(value) if isinstance(value, (list, dict)) else 1,
            "Not retained in this format; keep the .nadoc file to preserve this information.",
        )

    # Raw axis placement/phase is not encoded by either lattice exporter.
    add(
        "helix_geometry",
        "Helix coordinates and phase",
        len(design.helices),
        "Only lattice cells, nucleotide paths and insertions/deletions are exported. Absolute axis placement, phase and custom twist are reconstructed by the receiving application.",
    )
    token = hashlib.sha256(
        (target + json.dumps(current, sort_keys=True, separators=(",", ":"))).encode()
    ).hexdigest()
    return dict(
        format=target,
        issues=issues,
        blocked=any(i["severity"] == "error" for i in issues),
        token=token,
    )


def require_exportable(design, target):
    report = compatibility_report(design, target)
    if report["blocked"]:
        raise ValueError(
            "; ".join(
                i["label"] + ": " + i["effect"]
                for i in report["issues"]
                if i["severity"] == "error"
            )
        )
    return report
