"""Public editor-operation compiler for bounded MagicDNA caDNAno routing."""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from backend.core.models import LatticeType
from tools.magicdna.routing import inventory, read_graph, require, signature


def import_bundle(raw, lattice, *, name="MagicDNA bundle", upstream=None):
    """Reconstruct explicitly from cells, drawn domains, indels and crossovers.

    No imported graph/capture root, private diagnostic operation, automatic
    rerouting, forced ligation, or molecular-coordinate override is used.
    """
    from backend.api import headless_build as hb, state
    from backend.api.part_cell_commands import build as cell
    from backend.api.part_structural_commands import build as structural
    from backend.api.part_native_commands import build_loop
    from backend.api.part_proof_commands import PROOF_MINOR_KINDS
    from backend.api.crud import PlaceCrossoverRequest, _build_place_crossover
    from backend.core.part_history_contract import create_empty_part
    from backend.core.part_input_sources import embed, describe
    from scripts.agent_structure_guard import audit

    data, walks, source = read_graph(raw, lattice)
    inputs = {source.sha256: embed(source, raw)}
    upstream_source = None
    if upstream is not None:
        # Retain the complete independently audited upstream document, including
        # its input dependencies, when reconstructing a known derived export.
        audit(upstream)
        upstream_raw, _ = export_bundle(upstream)
        require(
            signature(json.loads(upstream_raw)) == signature(data),
            "Upstream routing differs: edited routes require recorded reconciliation",
        )
        encoded = upstream.model_dump_json().encode()
        upstream_source = describe(
            encoded, format="nadoc", media_type="application/json"
        )
        inputs[upstream_source.sha256] = embed(upstream_source, encoded)
    lt = LatticeType(lattice)
    identity = lambda label: str(uuid5(NAMESPACE_URL, source.sha256 + "/" + label))
    hs = sorted(data["vstrands"], key=lambda h: h["num"])
    hid = {h["num"]: identity(f"helix/{h['num']}") for h in hs}

    def record(kind, params, label, builder):
        params = {
            **params,
            "_generator": {
                "tool": "MagicDNA simple-bundle converter v1",
                "source": source.model_dump(mode="json"),
                "selection": label,
                "upstream": upstream_source.model_dump(mode="json")
                if upstream_source
                else None,
            },
        }
        fn = lambda d: builder(kind, d, params)
        if kind in PROOF_MINOR_KINDS:
            state.mutate_with_minor_log(
                op_subtype=kind, label=label, params=params, fn=fn
            )
        else:
            state.mutate_with_feature_log(kind, label, params, fn)

    def crossover(kind, design, params):
        updated, _, ligated = _build_place_crossover(
            design, PlaceCrossoverRequest.model_validate(params)
        )
        require(ligated, "AGENT_PROCESS_REQUIRED: source crossover did not ligate")
        return updated

    with hb.scratch_session(lt):
        empty = create_empty_part(name, lt).copy_with(input_sources=inputs)
        state.load_design(empty)
        for i, h in enumerate(hs):
            record(
                "helix-add-at-cell",
                dict(
                    row=h["row"],
                    col=h["col"],
                    length_bp=len(h["scaf"]),
                    populate_strands=False,
                    _helix_id=hid[h["num"]],
                ),
                f"Create bundle helix {i}",
                cell,
            )
        for i, h in enumerate(hs):
            for bp, (loop, skip) in enumerate(zip(h["loop"], h["skip"])):
                if loop or skip:
                    record(
                        "loop-skip-insert",
                        dict(helix_id=hid[h["num"]], bp_index=bp, delta=loop + skip),
                        f"Helix {i}: indel at bp {bp}",
                        build_loop,
                    )
        for number, (kind, walk) in enumerate(walks):
            domains = []
            for n, bp in walk:
                direction = "FORWARD" if (n % 2 == 0) == (kind == "scaf") else "REVERSE"
                if domains and domains[-1]["helix_id"] == hid[n]:
                    domains[-1]["end_bp"] = bp
                else:
                    domains.append(
                        dict(
                            helix_id=hid[n], start_bp=bp, end_bp=bp, direction=direction
                        )
                    )
            for j, domain in enumerate(domains):
                record(
                    "strand-add",
                    dict(
                        _strand_id=identity(f"strand/{number}/{j}"),
                        strand_type="scaffold" if kind == "scaf" else "staple",
                        domains=[domain],
                    ),
                    f"Draw {kind} {number + 1} domain {j + 1}",
                    structural,
                )
            for j, (a, b) in enumerate(zip(domains, domains[1:])):
                record(
                    "crossover-place",
                    dict(
                        crossover_id=identity(f"junction/{number}/{j}"),
                        half_a=dict(
                            helix_id=a["helix_id"],
                            index=a["end_bp"],
                            strand=a["direction"],
                        ),
                        half_b=dict(
                            helix_id=b["helix_id"],
                            index=b["start_bp"],
                            strand=b["direction"],
                        ),
                        nick_bp_a=a["end_bp"],
                        nick_bp_b=b["start_bp"]
                        - (1 if b["direction"] == "FORWARD" else -1),
                    ),
                    f"Connect {kind} {number + 1} domains {j + 1}/{j + 2}",
                    crossover,
                )
        design = state.get_or_404().model_copy(deep=True)
    from backend.core.cadnano import export_cadnano

    require(
        signature(export_cadnano(design)) == signature(data),
        "Reconstructed directed routing does not match source",
    )
    proof = audit(design)
    return design, {
        **inventory(data, walks),
        "audit": proof,
        "geometry": "Canonical NADOC straight lattice; caDNAno carries no MagicDNA 3D pose",
        "sequences": "Standard caDNAno contains no assigned DNA sequences; none inferred",
    }


def export_bundle(design):
    """Return ordinary caDNAno and a mandatory upstream-history sidecar.

    This deliberately rejects posed/deformed/annotated features that the basic
    MagicDNA route cannot represent. The source document remains authoritative.
    """
    import math
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.cadnano import export_cadnano
    from backend.core.lattice import (
        _lattice_position,
        _lattice_phase_offset,
        _lattice_direction,
        _lattice_twist,
    )
    from scripts.agent_structure_guard import audit

    audit(design)
    require(
        not (
            design.deformations
            or design.nucleotide_transforms
            or design.atomistic_reference
            or design.overhangs
            or design.extensions
            or design.cluster_joints
            or design.flexible_connections
            or design.duplexes
            or design.forced_ligations
        ),
        "Only ordinary straight bundle routing is supported",
    )
    require(
        all(
            not any(c.translation) and list(c.rotation) == [0, 0, 0, 1]
            for c in design.cluster_transforms
        ),
        "Posed clusters require a geometry bridge",
    )
    shift = None
    for h in design.helices:
        require(h.grid_pos is not None, "Missing lattice cell")
        x, y = _lattice_position(*h.grid_pos, design.lattice_type)
        delta = (
            h.axis_start.x - x,
            h.axis_start.y - y,
            h.axis_start.z - h.bp_start * BDNA_RISE_PER_BP,
        )
        if shift is None:
            shift = delta
        require(
            all(math.isclose(a, b, abs_tol=1e-8) for a, b in zip(delta, shift)),
            "Noncanonical bundle axes",
        )
        require(
            math.isclose(h.axis_end.x, h.axis_start.x, abs_tol=1e-8)
            and math.isclose(h.axis_end.y, h.axis_start.y, abs_tol=1e-8)
            and math.isclose(
                h.axis_end.z - h.axis_start.z,
                h.length_bp * BDNA_RISE_PER_BP,
                abs_tol=1e-8,
            ),
            "Noncanonical helix extent",
        )
        phase = _lattice_phase_offset(
            _lattice_direction(*h.grid_pos, design.lattice_type), design.lattice_type
        )
        phase += h.bp_start * _lattice_twist(design.lattice_type)
        require(
            math.isclose(h.phase_offset, phase, abs_tol=1e-8),
            "Noncanonical helical phase",
        )
        require(
            math.isclose(
                h.twist_per_bp_rad, _lattice_twist(design.lattice_type), abs_tol=1e-8
            ),
            "Noncanonical helical twist",
        )
    data = export_cadnano(design)
    # Bounded NADOC frame metadata is not understood by MagicDNA. The complete
    # source, sequences and history are carried by the sidecar instead.
    data.pop("nadoc_roundtrip", None)
    raw = json.dumps(data, separators=(",", ":")).encode()
    _, walks, _ = read_graph(raw, design.lattice_type)
    return raw, inventory(data, walks)


def write_export(design, destination):
    """Create a new package directory; never overwrite a source/user design."""
    from scripts.agent_structure_guard import publish

    raw, report = export_bundle(design)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        published = publish(design, destination / "source.nadoc")
        (destination / "routing.json").write_bytes(raw)
        manifest = {
            "schema": "nadoc-magicdna-simple-bundle-v1",
            "lattice": design.lattice_type.value,
            "routing": "routing.json",
            "source": "source.nadoc",
            "source_sha256": published["sha256"],
            **report,
            "geometry": "Routing-only interchange; each editor uses its native geometric convention",
            "sequence_policy": "Sequences and upstream construction are preserved in source.nadoc",
        }
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
    except Exception:
        # Only files in the newly created, exclusively owned package are ours.
        import shutil

        shutil.rmtree(destination)
        raise
    return manifest


def read_export(directory):
    """Return unchanged upstream authoring; reject edits needing reconciliation."""
    import hashlib
    from backend.core.models import Design
    from scripts.agent_structure_guard import audit
    from tools.magicdna.routing import digest

    root = Path(directory)
    m = json.loads((root / "manifest.json").read_text())
    require(
        m.get("schema") == "nadoc-magicdna-simple-bundle-v1", "Unknown bridge manifest"
    )
    require(
        m.get("source") == "source.nadoc" and m.get("routing") == "routing.json",
        "Invalid package paths",
    )
    source = (root / "source.nadoc").read_bytes()
    require(
        hashlib.sha256(source).hexdigest() == m["source_sha256"],
        "Upstream source digest mismatch",
    )
    design = Design.model_validate_json(source)
    require(design.lattice_type.value == m["lattice"], "Lattice mismatch")
    data, _, _ = read_graph((root / "routing.json").read_bytes(), m["lattice"])
    exported, _ = export_bundle(design)
    require(
        digest(data) == digest(json.loads(exported)) == m["routing_sha256"],
        "AGENT_PROCESS_REQUIRED: edited MagicDNA routing needs recorded reconciliation; original history cannot be discarded",
    )
    audit(design)
    return design
