"""Bounded NADOC lattice origins and sequences alongside ordinary caDNAno v2.

The optional ``nadoc_roundtrip`` extension contains no atom coordinates, phases,
reference structures, or arbitrary model fields. Its cells, bp origins/extents,
one common XY translation, and route-keyed sequences are sufficient to preserve
an unposed native honeycomb frame. Other readers can use the unchanged vstrands;
editing their topology invalidates this extension instead of applying stale data.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import Direction, LatticeType, Vec3

KEY = "nadoc_roundtrip"
_LIMIT = 16_384
_Address = Annotated[StrictInt, Field(ge=-1_000_000, le=1_000_000)]
_Index = Annotated[StrictInt, Field(ge=0, le=1_000_000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Helix(_Strict):
    num: _Index
    grid_pos: list[_Address] = Field(min_length=2, max_length=2)
    bp_start: _Address
    length_bp: StrictInt = Field(ge=1, le=2_048)


class _Sequence(_Strict):
    kind: Literal["scaf", "stap"]
    start: list[_Index] = Field(min_length=2, max_length=2)
    sequence: str = Field(min_length=1, max_length=_LIMIT, pattern=r"^[ACGTNacgtn]+$")


class _Metadata(_Strict):
    version: Literal[1]
    topology_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lattice_type: Literal["HONEYCOMB"]
    bp_offset: _Index
    translation_nm: list[float] = Field(min_length=2, max_length=2)
    helices: list[_Helix] = Field(min_length=1, max_length=32)
    sequences: list[_Sequence] = Field(max_length=256)

    @field_validator("translation_nm")
    @classmethod
    def finite_translation(cls, values):
        if any(not math.isfinite(v) or abs(v) > 1_000_000 for v in values):
            raise ValueError("NADOC caDNAno translation must be finite and bounded")
        return values


def topology_digest(data):
    """Bind restoration to routing, cell addresses, insertions and deletions."""
    fields = ("num", "row", "col", "scaf", "stap", "loop", "skip")
    topology = [{key: h[key] for key in fields}
                for h in sorted(data["vstrands"], key=lambda h: h["num"])]
    raw = json.dumps(topology, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def validate_roundtrip_metadata(data):
    """Validate the bounded extension against its actual caDNAno source graph."""
    if KEY not in data:
        return None
    meta = _Metadata.model_validate(data[KEY])
    if type(data[KEY].get("version")) is not int:
        raise ValueError("NADOC caDNAno metadata version must be an integer")
    if meta.bp_offset % 21:
        raise ValueError("NADOC caDNAno bp offset must preserve the 21-bp register")
    if meta.topology_sha256 != topology_digest(data):
        raise ValueError("NADOC caDNAno metadata does not match the source topology")
    by_num = {h["num"]: h for h in data["vstrands"]}
    records = {h.num: h for h in meta.helices}
    if len(records) != len(meta.helices) or set(records) != set(by_num):
        raise ValueError("NADOC caDNAno metadata must describe each source helix once")
    if sum(h.length_bp for h in meta.helices) > _LIMIT:
        raise ValueError("NADOC caDNAno restored helix spans exceed the import work contract")
    if any(len(h["scaf"]) % 21 for h in by_num.values()):
        raise ValueError("NADOC caDNAno metadata requires honeycomb source arrays")
    deltas, cells = set(), set()
    for num, record in records.items():
        source = by_num[num]
        row, col = record.grid_pos
        cells.add((row, col))
        deltas.add((source["row"] - row, source["col"] - col))
        if (row + col) % 2 != num % 2:
            raise ValueError("NADOC caDNAno metadata changes helix parity")
        occupied = [bp - meta.bp_offset for kind in ("scaf", "stap")
                    for bp, entry in enumerate(source[kind]) if entry != [-1] * 4]
        if not occupied or min(occupied) < record.bp_start or max(occupied) >= record.bp_start + record.length_bp:
            raise ValueError("NADOC caDNAno helix extent does not contain its source bases")
    if len(cells) != len(records) or len(deltas) != 1 or sum(next(iter(deltas))) % 2:
        raise ValueError("NADOC caDNAno cells must differ by one parity-preserving translation")
    seen, total = set(), 0
    for record in meta.sequences:
        key = (record.kind, *record.start)
        if key in seen:
            raise ValueError("NADOC caDNAno sequence route is duplicated")
        seen.add(key)
        num, bp = record.start
        if num not in by_num or bp >= len(by_num[num][record.kind]):
            raise ValueError("NADOC caDNAno sequence references a missing route")
        if by_num[num][record.kind][bp][:2] != [-1, -1] or by_num[num][record.kind][bp] == [-1] * 4:
            raise ValueError("NADOC caDNAno sequence must start at a source 5-prime end")
        visited, length = set(), 0
        while num != -1:
            if (num, bp) in visited:
                raise ValueError("NADOC caDNAno sequence route unexpectedly cycles")
            visited.add((num, bp))
            source = by_num[num]
            length += 1 + (source["loop"][bp] if bp < len(source["loop"]) else 0)
            length += source["skip"][bp] if bp < len(source["skip"]) else 0
            num, bp = source[record.kind][bp][2:]
        total += length
        if length != len(record.sequence) or total > _LIMIT:
            raise ValueError("NADOC caDNAno sequence length does not match its source route")
    return meta


def has_roundtrip_metadata(data):
    """True only for validated metadata that restores the original native frame."""
    return validate_roundtrip_metadata(data) is not None


def _identity_pose(item):
    return (all(abs(x) < 1e-12 for x in item.translation)
            and all(abs(x - y) < 1e-12 for x, y in zip(item.rotation, (0, 0, 0, 1))))


def _native_frame(design):
    """Describe a bounded canonical frame, or decline the exact-roundtrip claim."""
    if design.lattice_type != LatticeType.HONEYCOMB:
        return None
    if (not design.helices or len(design.helices) > 32
            or any(h.length_bp > 2_048 for h in design.helices)
            or sum(h.length_bp for h in design.helices) > _LIMIT
            or len(design.strands) > 256
            or len({h.lattice_frame_id for h in design.helices}) > 1):
        return None
    if (design.deformations or design.nucleotide_transforms or design.atomistic_reference
            or design.cluster_joints or design.duplexes or design.flexible_connections
            or any(not _identity_pose(c) for c in design.cluster_transforms)
            or any(not _identity_pose(o) for o in design.overhangs)
            or any(d.rotation_theta_deg or d.rotation_phi_deg for o in design.overhangs for d in o.sub_domains)):
        return None
    from backend.core.deformation import effective_helix_for_geometry
    from backend.core.lattice import _lattice_position, _lattice_phase_offset, _lattice_twist
    records, shifts = [], []
    occupied = {}
    assigned = 0
    for strand in design.strands:
        if not strand.domains:
            return None
        if strand.sequence is not None:
            assigned += len(strand.sequence)
            if not strand.sequence or set(strand.sequence.upper()) - set("ACGTN"):
                return None
        for domain in strand.domains:
            values = occupied.setdefault(domain.helix_id, [])
            values.extend((domain.start_bp, domain.end_bp))
    if assigned > _LIMIT:
        return None
    all_bounds = [bp for bounds in occupied.values() for bp in bounds]
    if not all_bounds:
        return None
    bp_offset = max(0, math.ceil(-min(all_bounds) / 21) * 21)
    width = math.ceil((max(all_bounds) + bp_offset + 1) / 21) * 21
    if width > 2_048 or width * len(design.helices) > _LIMIT:
        return None
    twist = _lattice_twist(design.lattice_type)
    for helix in design.helices:
        if helix.grid_pos is None or helix.native_residues:
            return None
        span = occupied.get(helix.id, [])
        if (not span or min(span) < helix.bp_start
                or max(span) >= helix.bp_start + helix.length_bp):
            return None
        h = effective_helix_for_geometry(helix, design)
        row, col = helix.grid_pos
        direction = Direction.FORWARD if (row + col) % 2 == 0 else Direction.REVERSE
        x, y = _lattice_position(row, col, design.lattice_type)
        expected_phase = _lattice_phase_offset(direction, design.lattice_type) + h.bp_start * twist
        phase_error = math.remainder(h.phase_offset - expected_phase, 2 * math.pi)
        expected = (h.axis_start.x, h.axis_start.y, h.bp_start * BDNA_RISE_PER_BP,
                    h.axis_start.x, h.axis_start.y, (h.bp_start + h.length_bp) * BDNA_RISE_PER_BP)
        actual = (*h.axis_start.to_array(), *h.axis_end.to_array())
        if (any(abs(a - b) > 1e-9 for a, b in zip(actual, expected))
                or abs(phase_error) > 1e-9 or abs(h.twist_per_bp_rad - twist) > 1e-12):
            return None
        shifts.append((h.axis_start.x - x, h.axis_start.y - y))
        records.append(dict(helix_id=h.id, grid_pos=[row, col],
                            bp_start=h.bp_start, length_bp=h.length_bp))
    if any(abs(v - w) > 1e-9 for shift in shifts for v, w in zip(shift, shifts[0])):
        return None
    if any(not math.isfinite(x) or abs(x) > 1_000_000 for x in shifts[0]):
        return None
    return records, shifts[0]


def supports_native_roundtrip_frame(design):
    """Preflight for the export dialog; it never calls the exporter recursively."""
    return _native_frame(design) is not None


def attach_roundtrip_metadata(data, design, layout):
    """Attach exact native-frame metadata only when that guarantee is representable.

    Posed/bent/atom-reference designs retain the existing standard export policy;
    they receive no exact-frame claim. No placement is fitted or modified here.
    """
    frame = _native_frame(design)
    if frame is None:
        return data
    records, shift = frame
    records = [dict(num=layout["helix_num_map"][r["helix_id"]],
                    **{k: v for k, v in r.items() if k != "helix_id"}) for r in records]
    sequences = []
    for strand in design.strands:
        if strand.sequence is None:
            continue
        domain = strand.domains[0]
        sequences.append(dict(kind="scaf" if strand.is_scaffold else "stap",
            start=[layout["helix_num_map"][domain.helix_id], domain.start_bp + layout["offset"]],
            sequence=strand.sequence))
    candidate = dict(data)
    candidate[KEY] = dict(version=1, topology_sha256=topology_digest(data),
        lattice_type="HONEYCOMB", bp_offset=layout["offset"], translation_nm=list(shift),
        helices=records, sequences=sequences)
    # Ineligible sizes/empty tracks remain ordinary v2, rather than promising a
    # frame that the bounded recorded importer cannot reproduce.
    try:
        validate_roundtrip_metadata(candidate)
    except ValueError:
        return data
    return candidate


def restore_roundtrip_metadata(data, helices, strands, lattice, helix_by_num):
    """Restore only declared native lattice coordinates and route-owned sequences."""
    meta = validate_roundtrip_metadata(data)
    if meta is None:
        return helices, strands
    if lattice != LatticeType.HONEYCOMB:
        raise ValueError("NADOC caDNAno metadata requires the honeycomb lattice")
    from backend.core.lattice import _lattice_position, _lattice_phase_offset, _lattice_twist
    records = {helix_by_num[h.num].id: h for h in meta.helices}
    num_by_id = {h.id: num for num, h in helix_by_num.items()}
    sequences = {(s.kind, *s.start): s.sequence for s in meta.sequences}
    restored_helices, restored_strands = [], []
    twist = _lattice_twist(lattice)
    for h in helices:
        record = records[h.id]
        row, col = record.grid_pos
        direction = Direction.FORWARD if (row + col) % 2 == 0 else Direction.REVERSE
        x, y = _lattice_position(row, col, lattice)
        x += meta.translation_nm[0]
        y += meta.translation_nm[1]
        restored_helices.append(h.model_copy(update=dict(grid_pos=(row, col),
            bp_start=record.bp_start, length_bp=record.length_bp,
            axis_start=Vec3(x=x, y=y, z=record.bp_start * BDNA_RISE_PER_BP),
            axis_end=Vec3(x=x, y=y, z=(record.bp_start + record.length_bp) * BDNA_RISE_PER_BP),
            phase_offset=_lattice_phase_offset(direction, lattice) + record.bp_start * twist,
            twist_per_bp_rad=twist, direction=direction,
            loop_skips=[ls.model_copy(update={"bp_index": ls.bp_index - meta.bp_offset}) for ls in h.loop_skips])))
    for strand in strands:
        first = strand.domains[0]
        key = ("scaf" if strand.is_scaffold else "stap", num_by_id[first.helix_id], first.start_bp)
        restored_strands.append(strand.model_copy(update=dict(sequence=sequences.get(key),
            domains=[d.model_copy(update={"start_bp": d.start_bp - meta.bp_offset,
                                         "end_bp": d.end_bp - meta.bp_offset}) for d in strand.domains])))
    return restored_helices, restored_strands
