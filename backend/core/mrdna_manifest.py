"""Versioned identity contract for NADOC ↔ mrDNA jobs.

The manifest is deliberately independent of DCD/PSF decoding.  Model construction
must write it before a job can run; all later reconstruction and metrics consume it.
Helix/bp labels are render metadata, never the primary simulation identity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


MRDNA_MANIFEST_SCHEMA = 1
MRDNA_MANIFEST_FILE = "nucleotide_map.json"


class MrdnaNucleotideIdentity(BaseModel):
    strand_id: str
    segment_kind: Literal["domain", "extension", "crossover_insert"]
    segment_id: str
    nucleotide_ordinal: int = Field(ge=0)
    copy: int = Field(default=0, ge=0)

    def key(self) -> str:
        return json.dumps(
            [
                self.strand_id,
                self.segment_kind,
                self.segment_id,
                self.nucleotide_ordinal,
                self.copy,
            ],
            separators=(",", ":"),
        )


class MrdnaRenderAddress(BaseModel):
    helix_id: str
    bp_index: int | str
    direction: str | int
    copy: int = Field(default=0, ge=0)

    def key(self) -> str:
        if self.helix_id == "__xb__":
            return f"__xb__:{self.bp_index}:{self.direction}"
        suffix = f":{self.copy}" if self.copy else ""
        return f"{self.helix_id}:{self.bp_index}:{self.direction}{suffix}"


class MrdnaParticleBinding(BaseModel):
    particle_index: int = Field(ge=0)
    particle_kind: Literal["DNA", "NAS", "synthetic"]
    weight: float = Field(default=1.0, gt=0.0, le=1.0)


class MrdnaNucleotideRecord(BaseModel):
    identity: MrdnaNucleotideIdentity
    render: MrdnaRenderAddress
    strand_type: str
    classification: Literal[
        "duplex",
        "unpaired",
        "overhang",
        "extension",
        "linker",
        "loop_copy",
        "crossover_insert",
    ]
    simulation_mode: Literal["direct", "interpolated"]
    model_nucleotide_index: int = Field(ge=0)
    particle_bindings: list[MrdnaParticleBinding] = Field(default_factory=list)
    predecessor: str | None = None
    successor: str | None = None
    pair: str | None = None

    @model_validator(mode="after")
    def _direct_has_particle(self) -> "MrdnaNucleotideRecord":
        if self.simulation_mode == "direct" and not self.particle_bindings:
            raise ValueError("direct nucleotide has no particle binding")
        return self


class MrdnaNucleotideManifest(BaseModel):
    schema_version: Literal[1] = MRDNA_MANIFEST_SCHEMA
    design_fingerprint: str
    records: list[MrdnaNucleotideRecord]

    @model_validator(mode="after")
    def _identity_graph_is_consistent(self) -> "MrdnaNucleotideManifest":
        by_id: dict[str, MrdnaNucleotideRecord] = {}
        render_keys: set[str] = set()
        for record in self.records:
            ident = record.identity.key()
            if ident in by_id:
                raise ValueError(f"duplicate nucleotide identity {ident}")
            by_id[ident] = record
            render = record.render.key()
            if render in render_keys:
                raise ValueError(f"duplicate render address {render}")
            render_keys.add(render)

        for ident, record in by_id.items():
            for edge_name in ("predecessor", "successor", "pair"):
                target = getattr(record, edge_name)
                if target is not None and target not in by_id:
                    raise ValueError(f"{ident} has missing {edge_name} target {target}")
            if record.successor is not None:
                other = by_id[record.successor]
                if other.predecessor != ident:
                    raise ValueError(f"non-reciprocal strand edge {ident} → {record.successor}")
            if record.pair is not None and by_id[record.pair].pair != ident:
                raise ValueError(f"non-reciprocal base pair {ident} ↔ {record.pair}")
        return self

    def write(self, job_dir: Path) -> Path:
        path = job_dir / MRDNA_MANIFEST_FILE
        path.write_text(self.model_dump_json(indent=2))
        return path

    @classmethod
    def load_required(cls, job_dir: Path) -> "MrdnaNucleotideManifest":
        path = job_dir / MRDNA_MANIFEST_FILE
        if not path.exists():
            raise RuntimeError(
                "Unsupported mrDNA job: nucleotide_map.json is missing; rerun the job"
            )
        return cls.model_validate_json(path.read_text())


def build_mrdna_nucleotide_manifest(
    design, *, design_fingerprint: str
) -> MrdnaNucleotideManifest:
    """Build the manifest from mrDNA's exact nucleotide enumeration.

    This intentionally calls the same private enumerator used to construct the
    model. It must never independently walk domains or rediscover topology.
    Particle bindings are added by the trajectory-decoder phase; at this boundary
    every nucleotide is explicitly marked interpolated rather than falsely direct.
    """
    from backend.core.mrdna_bridge import _build_nt_arrays

    (
        _r,
        bp,
        _stack,
        three_prime,
        _orientation,
        _sequence,
        _nt_key,
        metadata,
        _strand_sequences,
    ) = _build_nt_arrays(design, return_nt_key=True, return_identity=True)
    if len(metadata) != len(bp):
        raise ValueError(
            f"mrDNA identity enumeration mismatch: {len(metadata)} identities for {len(bp)} nucleotides"
        )

    identities = [
        MrdnaNucleotideIdentity(
            strand_id=item["strand_id"],
            segment_kind=item["segment_kind"],
            segment_id=item["segment_id"],
            nucleotide_ordinal=item["nucleotide_ordinal"],
            copy=item["copy"],
        )
        for item in metadata
    ]
    identity_keys = [identity.key() for identity in identities]
    predecessor: list[int | None] = [None] * len(metadata)
    for i, nxt in enumerate(three_prime):
        if int(nxt) >= 0:
            predecessor[int(nxt)] = i

    records = []
    for i, item in enumerate(metadata):
        nxt = int(three_prime[i])
        partner = int(bp[i])
        records.append(
            MrdnaNucleotideRecord(
                identity=identities[i],
                render=MrdnaRenderAddress(
                    helix_id=item["helix_id"],
                    bp_index=item["bp_index"],
                    direction=item["direction"],
                    copy=item["copy"],
                ),
                strand_type=item["strand_type"],
                classification=item["classification"],
                simulation_mode="interpolated",
                model_nucleotide_index=i,
                predecessor=(
                    identity_keys[predecessor[i]] if predecessor[i] is not None else None
                ),
                successor=identity_keys[nxt] if nxt >= 0 else None,
                pair=identity_keys[partner] if partner >= 0 else None,
            )
        )
    return MrdnaNucleotideManifest(
        design_fingerprint=design_fingerprint, records=records
    )


def bind_manifest_to_mrdna_particles(
    manifest: MrdnaNucleotideManifest, model
) -> MrdnaNucleotideManifest:
    """Bind identities to model particles using instrumented segment contours.

    One nucleotide can lie between two coarse particles; those bindings are
    interpolation weights, not claims that a coarse bead directly resolves a base.
    A one-particle segment receives that particle at weight 1. Particle indices are
    mrDNA's written PSF/DCD indices.
    """
    by_model_index = {record.model_nucleotide_index: record for record in manifest.records}
    updates: dict[int, tuple[list[MrdnaParticleBinding], str]] = {}
    for segment in getattr(model, "children", []):
        sources = getattr(segment, "_nadoc_source_nucleotides", None)
        beads = [
            bead for bead in getattr(segment, "beads", [])
            if getattr(bead, "name", None) in {"DNA", "NAS"}
            and getattr(bead, "idx", None) is not None
        ]
        if not sources or not beads:
            continue
        beads.sort(key=lambda bead: float(bead.contour_position))
        contours = [float(bead.contour_position) for bead in beads]
        for source in sources:
            source_index = source["model_nucleotide_index"]
            if source_index not in by_model_index:
                continue
            target = float(segment.nt_pos_to_contour(source["segment_nt_index"]))
            if len(beads) == 1 or target <= contours[0]:
                chosen = [(beads[0], 1.0)]
            elif target >= contours[-1]:
                chosen = [(beads[-1], 1.0)]
            else:
                right = next(i for i, value in enumerate(contours) if value >= target)
                left = right - 1
                span = contours[right] - contours[left]
                fraction = (target - contours[left]) / span if span > 1e-12 else 0.0
                chosen = [(beads[left], 1.0 - fraction), (beads[right], fraction)]
            bindings = [
                MrdnaParticleBinding(
                    particle_index=int(bead.idx),
                    particle_kind="DNA" if bead.name == "DNA" else "NAS",
                    weight=max(float(weight), 1e-12),
                )
                for bead, weight in chosen
                if weight > 1e-12
            ]
            mode = (
                "direct"
                if len(bindings) == 1
                and bindings[0].weight == 1.0
                and float(getattr(chosen[0][0], "num_nt", 2)) <= 1.0
                else "interpolated"
            )
            updates[source_index] = (bindings, mode)

    records = []
    for record in manifest.records:
        bindings, mode = updates.get(
            record.model_nucleotide_index, (record.particle_bindings, record.simulation_mode)
        )
        records.append(
            record.model_copy(
                update={"particle_bindings": bindings, "simulation_mode": mode}
            )
        )
    return MrdnaNucleotideManifest(
        design_fingerprint=manifest.design_fingerprint, records=records
    )
