"""Canonical NADOC nucleotide keys and design/atomistic resolution.

This module is the backend authority for the grammar defined by
``frontend/src/scene/base_ref.js``.  Parsing is deliberately from the right:
real and synthetic owner ids may themselves contain colons.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import TYPE_CHECKING, Any

from backend.core.models import Design

if TYPE_CHECKING:
    from backend.core.atomistic import AtomisticModel

XB_HELIX = "__xb__"
_INT_RE = re.compile(r"^-?\d+$")
_NONNEG_INT_RE = re.compile(r"^\d+$")
_DIRECTIONS = frozenset({"FORWARD", "REVERSE", "forward", "reverse"})


@dataclass(frozen=True, slots=True)
class ParsedBaseKey:
    helix_id: str
    bp_index: int | None = None
    direction: str | None = None
    copy: int = 0
    crossover_id: str | None = None
    k: int | None = None

    @property
    def family(self) -> str:
        if self.helix_id == XB_HELIX:
            return "xover"
        if self.helix_id.startswith("__lnk__"):
            return "sslink"
        if self.helix_id.startswith("__ext_"):
            return "extension"
        return "backbone"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        if self.helix_id == XB_HELIX:
            return {k: out[k] for k in ("helix_id", "crossover_id", "k")}
        return {k: out[k] for k in ("helix_id", "bp_index", "direction", "copy")}


@dataclass(frozen=True, slots=True)
class ResolvedBase:
    key: str
    parsed: ParsedBaseKey
    base: str
    strand_id: str
    source_class: str
    owner_id: str
    domain_index: int | None
    residue_atom_names: tuple[str, ...]
    atom_serials: dict[str, int]
    atom_positions_nm: dict[str, tuple[float, float, float]]

    @property
    def is_extra(self) -> bool:
        return self.source_class in {
            "crossover-extra",
            "extension",
            "loop-copy",
            "linker",
        }

    @property
    def has_cpd_atoms(self) -> bool:
        return "C5" in self.atom_serials and "C6" in self.atom_serials

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "parsed": self.parsed.to_dict(),
            "base": self.base,
            "strand_id": self.strand_id,
            "source_class": self.source_class,
            "owner_id": self.owner_id,
            "domain_index": self.domain_index,
            "residue_atom_names": list(self.residue_atom_names),
            "has_c5_c6": self.has_cpd_atoms,
        }


def parse_base_key(key: object) -> ParsedBaseKey | None:
    """Parse one canonical key, rejecting ambiguous/non-integral forms."""
    if not isinstance(key, str) or not key:
        return None
    if key.startswith(f"{XB_HELIX}:"):
        rest = key[len(XB_HELIX) + 1 :]
        owner, sep, tail = rest.rpartition(":")
        if not sep or not owner or not _NONNEG_INT_RE.fullmatch(tail):
            return None
        return ParsedBaseKey(helix_id=XB_HELIX, crossover_id=owner, k=int(tail))

    # Optional copy is recognized only after a valid direction token, avoiding
    # ambiguity when a helix id ends in numeric colon-delimited components.
    head, sep, tail = key.rpartition(":")
    if not sep:
        return None
    copy = 0
    if _NONNEG_INT_RE.fullmatch(tail):
        copy = int(tail)
        if copy == 0:
            return None
        head, sep, direction = head.rpartition(":")
        if not sep:
            return None
    else:
        direction = tail
    if direction not in _DIRECTIONS:
        return None
    helix_id, sep, bp_text = head.rpartition(":")
    if not sep or not helix_id or not _INT_RE.fullmatch(bp_text):
        return None
    return ParsedBaseKey(
        helix_id=helix_id, bp_index=int(bp_text), direction=direction, copy=copy
    )


def base_family(key: object) -> str | None:
    parsed = parse_base_key(key)
    return parsed.family if parsed else None


def atom_base_key(atom: object) -> str | None:
    """Return the canonical key carried by an atomistic provenance record."""
    crossover_id = getattr(atom, "crossover_id", None)
    extra_k = getattr(atom, "extra_base_k", None)
    if crossover_id is not None and extra_k is not None:
        return f"{XB_HELIX}:{crossover_id}:{int(extra_k)}"
    extension_id = getattr(atom, "extension_id", None)
    ext_k = getattr(atom, "ext_k", None)
    if extension_id is not None and ext_k is not None:
        return f"__ext_{extension_id}:{int(ext_k)}:{getattr(atom, 'direction', '')}"
    helix_id = getattr(atom, "helix_id", None)
    if not helix_id:
        return None
    key = f"{helix_id}:{int(getattr(atom, 'bp_index'))}:{getattr(atom, 'direction')}"
    copy = int(getattr(atom, "copy_k", 0) or 0)
    return f"{key}:{copy}" if copy else key


def _group_atomistic(model: "AtomisticModel") -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = {}
    for atom in model.atoms:
        key = atom_base_key(atom)
        if key:
            grouped.setdefault(key, []).append(atom)
    return grouped


def _structural_owner(
    design: Design, parsed: ParsedBaseKey
) -> tuple[str, str, str, int | None] | None:
    """Return ``(base, strand_id, owner_id, domain_index)`` without atom serials."""
    if parsed.helix_id == XB_HELIX:
        owners = [*design.crossovers, *design.forced_ligations]
        owner = next((item for item in owners if item.id == parsed.crossover_id), None)
        seq = owner.extra_bases if owner is not None else None
        if owner is None or seq is None or parsed.k is None or parsed.k >= len(seq):
            return None
        strand_id = getattr(owner, "strand_id", None) or ""
        return seq[parsed.k].upper(), strand_id, owner.id, None

    if parsed.helix_id.startswith("__ext_"):
        extension_id = parsed.helix_id[len("__ext_") :]
        ext = next(
            (item for item in design.extensions if item.id == extension_id), None
        )
        seq = ext.sequence if ext is not None else None
        if (
            ext is None
            or seq is None
            or parsed.bp_index is None
            or not (0 <= parsed.bp_index < len(seq))
        ):
            return None
        # Extension atom provenance carries the anchor direction; reject a stale
        # key with the wrong polarity by checking the terminal domain.
        strand = design.find_strand(ext.strand_id)
        if strand is None or not strand.domains:
            return None
        terminal = strand.domains[0] if ext.end == "five_prime" else strand.domains[-1]
        if terminal.direction.value.upper() != parsed.direction.upper():
            return None
        return seq[parsed.bp_index].upper(), strand.id, ext.id, None

    from backend.core.sequences import _build_loop_skip_map, domain_bp_range

    ls_map = _build_loop_skip_map(design)
    for strand in design.strands:
        offset = 0
        for domain_index, domain in enumerate(strand.domains):
            for bp in domain_bp_range(domain):
                delta = ls_map.get((domain.helix_id, bp), 0)
                copies = 0 if delta <= -1 else delta + 1
                copy_order = (
                    range(copies)
                    if domain.direction.value == "FORWARD"
                    else range(copies - 1, -1, -1)
                )
                for copy in copy_order:
                    base = (
                        (strand.sequence or "")[offset]
                        if offset < len(strand.sequence or "")
                        else "N"
                    )
                    if (
                        domain.helix_id == parsed.helix_id
                        and bp == parsed.bp_index
                        and domain.direction.value.upper() == parsed.direction.upper()
                        and copy == parsed.copy
                    ):
                        return base.upper(), strand.id, domain.helix_id, domain_index
                    offset += 1
    return None


def resolve_base_keys(
    design: Design,
    keys: list[str] | tuple[str, ...],
    *,
    atomistic_model: "AtomisticModel | None" = None,
    require_atoms: bool = True,
) -> tuple[list[ResolvedBase], list[dict[str, str]]]:
    """Resolve keys against current design ownership and stable atom provenance."""
    if atomistic_model is None and require_atoms:
        from backend.core.atomistic import build_atomistic_model

        atomistic_model = build_atomistic_model(design)
    grouped = _group_atomistic(atomistic_model) if atomistic_model is not None else {}
    resolved: list[ResolvedBase] = []
    errors: list[dict[str, str]] = []
    for key in keys:
        parsed = parse_base_key(key)
        if parsed is None:
            errors.append(
                {
                    "code": "invalid_base_key",
                    "key": str(key),
                    "message": "Invalid canonical base key.",
                }
            )
            continue
        owner = _structural_owner(design, parsed)
        if owner is None:
            errors.append(
                {
                    "code": "stale_base_key",
                    "key": key,
                    "message": "Base key no longer resolves in this design.",
                }
            )
            continue
        base, strand_id, owner_id, domain_index = owner
        atoms = grouped.get(key, [])
        if not atoms and parsed.helix_id != XB_HELIX and parsed.direction is not None:
            canonical = (
                f"{parsed.helix_id}:{parsed.bp_index}:{parsed.direction.upper()}"
                f"{f':{parsed.copy}' if parsed.copy else ''}"
            )
            atoms = grouped.get(canonical, [])
        if require_atoms and not atoms:
            errors.append(
                {
                    "code": "missing_atomistic_residue",
                    "key": key,
                    "message": "No production atomistic residue carries this base key.",
                }
            )
            continue
        by_name = {getattr(atom, "name"): atom for atom in atoms}
        source_class = (
            "crossover-extra"
            if parsed.helix_id == XB_HELIX
            else "extension"
            if parsed.helix_id.startswith("__ext_")
            else "linker"
            if parsed.helix_id.startswith("__lnk__")
            else "loop-copy"
            if parsed.copy
            else "ordinary"
        )
        positions = {
            name: (float(atom.x), float(atom.y), float(atom.z))
            for name, atom in by_name.items()
        }
        resolved.append(
            ResolvedBase(
                key=key,
                parsed=parsed,
                base=base,
                strand_id=strand_id
                or (getattr(atoms[0], "strand_id", "") if atoms else ""),
                source_class=source_class,
                owner_id=owner_id,
                domain_index=domain_index,
                residue_atom_names=tuple(sorted(by_name)),
                atom_serials={name: int(atom.serial) for name, atom in by_name.items()},
                atom_positions_nm=positions,
            )
        )
    return resolved, errors


def distance_nm(a: ResolvedBase, b: ResolvedBase, atom_name: str) -> float | None:
    return atom_distance_nm(a, atom_name, b, atom_name)


def atom_distance_nm(
    a: ResolvedBase, atom_name_a: str, b: ResolvedBase, atom_name_b: str
) -> float | None:
    """Distance between explicitly named endpoint atoms, if both are present."""

    pa = a.atom_positions_nm.get(atom_name_a)
    pb = b.atom_positions_nm.get(atom_name_b)
    if pa is None or pb is None:
        return None
    return math.dist(pa, pb)
