"""Bounded offline N → M → D experiment, not a production motion compiler.

M is a diagnostic whole-helix world motion. D is an existing native composed
translation of one base. Native prefix/suffix outputs are captured once; changing
M never reruns history. New material, replacement/reset and companion policy are
deliberately outside this admitted experiment.
"""
from copy import deepcopy
from dataclasses import dataclass, fields
import hashlib

import numpy as np
from scipy.spatial.transform import Rotation

from backend.api import part_proof_commands as commands
from backend.core.atomistic import Atom, build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.api.part_group_geometry_budget import require_group_geometry_budget
from tools.member_motion_audit import M, _full_motion, _point


def _key(value):
    get = value.get if isinstance(value, dict) else lambda key, default=None: getattr(value, key, default)
    return get("helix_id"), get("bp_index"), get("direction"), get("copy_k") or 0


def existing_material_union(prefix, targets):
    """Resolve ordinary material present now, not descendant/birth policy.

    Native selector ranges may include unoccupied partner directions. Intersect
    them with actual native records and deduplicate the resulting identities,
    preserving record order. This diagnostic inventory applies no motion.
    """
    from backend.core.part_group_selection import resolve_deformation_targets

    require_group_geometry_budget(prefix, max_work=1024)
    if prefix.extensions or prefix.crossovers or prefix.overhangs:
        raise ValueError("Companion ancestry is outside this ordinary-material inventory")
    ranges = resolve_deformation_targets(prefix, targets)
    records = _geometry_for_design(prefix)
    keys = [_key(row) for row in records]
    if len(keys) != len(set(keys)):
        raise ValueError("Native material identities are not unique")
    selected = []
    for row, key in zip(records, keys, strict=True):
        for scope in ranges:
            if (row["helix_id"] != scope.helix_id or row["direction"] != scope.direction.value
                    or not min(scope.start_bp, scope.end_bp) <= row["bp_index"] <= max(scope.start_bp, scope.end_bp)):
                continue
            if scope.strand_id is not None and (
                    row["strand_id"] != scope.strand_id or row["domain_index"] != scope.domain_index):
                continue
            selected.append(key)
            break
    if not selected:
        raise ValueError("Selection contains no existing ordinary material")
    return tuple(selected)


@dataclass(frozen=True)
class OrderedProbe:
    source_sha256: str
    suffix_feature_id: str
    selected_helix_ids: tuple[str, ...]
    target: tuple
    translation: tuple[float, float, float]
    _prefix_records: list
    _prefix_atoms: object
    _native_after_records: list
    _native_after_atoms: object
    _named_targets: list | None = None

    def evaluate(self, *, motion_enabled=True):
        """Detached candidate only; no source model or command is published."""
        if not motion_enabled:
            # An absent diagnostic event retains the exact native suffix,
            # including float representations and native quaternion choices.
            return deepcopy(self._native_after_records), deepcopy(self._native_after_atoms), [
                {"feature_id": self.suffix_feature_id, "kind": "native-compose-translation",
                 "target": self.target, "native_output_exact": True}]
        records = deepcopy(self._prefix_records)
        atoms = deepcopy(self._prefix_atoms)
        for helix_id in self.selected_helix_ids:
            records = _full_motion(records, helix_id)
        selected = set(self.selected_helix_ids)
        for atom in atoms.atoms:
            if atom.helix_id in selected:
                atom.x, atom.y, atom.z = _point([atom.x, atom.y, atom.z])
        target_moved = self.target[0] in selected
        if target_moved:
            for record in records:
                if _key(record) != self.target:
                    continue
                for name in ("backbone_position", "base_position", "slab_position"):
                    record[name] = (np.asarray(record[name]) + self.translation).tolist()
                site = record["helical_site"]
                site["axis_point"] = (np.asarray(site["axis_point"]) + self.translation).tolist()
            for atom in atoms.atoms:
                if _key(atom) == self.target:
                    atom.x, atom.y, atom.z = (np.asarray([atom.x, atom.y, atom.z]) + self.translation).tolist()
        else:
            # The native suffix owns an unselected base; carry its exact output.
            records = [deepcopy(after) if _key(after) == self.target else record
                       for record, after in zip(records, self._native_after_records, strict=True)]
            atoms.atoms = [deepcopy(after) if _key(after) == self.target else atom
                           for atom, after in zip(atoms.atoms, self._native_after_atoms.atoms, strict=True)]
        return records, atoms, [
            {"feature_id": "diagnostic-world-M", "kind": "world-motion",
             "source_namespace": "helix", "source_ids": list(self.selected_helix_ids),
             "named_targets": deepcopy(self._named_targets),
             "material_keys": [_key(r) for r in self._prefix_records if r["helix_id"] in selected],
             "pose": deepcopy(M), "frame": "world", "prefix_sha256": self.source_sha256},
            {"feature_id": self.suffix_feature_id, "kind": "native-compose-translation",
             "target": self.target, "translation": self.translation, "frame": "world",
             "after_event": "diagnostic-world-M"}]


def compile_ordered_probe(prefix, suffix_entry, selected_helix_ids, *, named_targets=None):
    """Admit one exact existing native suffix and a diagnostic selection union."""
    if suffix_entry.op_kind != "nucleotide-transform":
        raise ValueError("Only an existing native nucleotide-transform suffix is admitted")
    params = deepcopy(suffix_entry.params)
    if (params.get("kind") != "base" or params.get("compose") is not True
            or params.get("rotation") != [0, 0, 0, 1] or params.get("copy_k", 0) != 0):
        raise ValueError("Only composed world translation is admitted; replacement/reset/rotation remain unresolved")
    companions = ("extensions", "crossovers", "forced_ligations", "overhangs", "overhang_bindings",
                  "overhang_connections", "flexible_connections", "flexible_segment_marks",
                  "photoproduct_junctions", "cluster_joints",
                  "cluster_join_constraints", "duplexes")
    if any(getattr(prefix, name) for name in companions):
        raise ValueError("Companion, constraint and birth policy is outside this ordering probe")
    selected = tuple(sorted(set(selected_helix_ids)))
    if not selected or not set(selected) <= {h.id for h in prefix.helices}:
        raise ValueError("Expected an exact nonempty whole-helix selection")
    require_group_geometry_budget(prefix, max_work=1024)
    captured = prefix.model_dump_json()
    after = commands.execute("nucleotide-transform", prefix.model_copy(deep=True), params)
    before_records, after_records = _geometry_for_design(prefix), _geometry_for_design(after)
    if named_targets is not None:
        material = existing_material_union(prefix, named_targets)
        expected = tuple(_key(row) for row in before_records if row["helix_id"] in selected)
        if material != expected:
            raise ValueError("Named selection is not the admitted whole-helix material; partial frames remain unresolved")
    before_atoms, after_atoms = (build_atomistic_model(model, fast_bridges=True) for model in (prefix, after))
    if len(before_records) + len(before_atoms.atoms) > 65_536:
        raise ValueError("Offline ordering probe exceeds its fixed material budget")
    identity = [field.name for field in fields(Atom) if field.name not in {"x", "y", "z"}]
    if ([tuple(getattr(a, field) for field in identity) for a in before_atoms.atoms]
            != [tuple(getattr(a, field) for field in identity) for a in after_atoms.atoms]
            or before_atoms.bonds != after_atoms.bonds
            or [_key(r) for r in before_records] != [_key(r) for r in after_records]):
        raise ValueError("Native suffix changed material identity or topology; birth is not admitted")
    target = params["helix_id"], params["bp_index"], params["direction"], 0
    if target not in {_key(r) for r in before_records}:
        raise ValueError("Suffix target is absent from the compiled prefix")
    translation = np.asarray(params["translation"])
    for before, final in zip(before_records, after_records, strict=True):
        if _key(before) != target:
            if before != final:
                raise ValueError("Native suffix affected material outside its declared base")
        else:
            for name in ("backbone_position", "base_position", "slab_position"):
                np.testing.assert_allclose(final[name], np.asarray(before[name]) + translation, rtol=0, atol=1e-10)
            for name in ("base_normal", "axis_tangent"):
                np.testing.assert_allclose(final[name], before[name], rtol=0, atol=1e-10)
            np.testing.assert_allclose(Rotation.from_quat(final["slab_quaternion"]).as_matrix(),
                                       Rotation.from_quat(before["slab_quaternion"]).as_matrix(), rtol=0, atol=1e-10)
            before_site, final_site = before["helical_site"], final["helical_site"]
            np.testing.assert_allclose(final_site["axis_point"],
                                       np.asarray(before_site["axis_point"]) + translation, rtol=0, atol=1e-10)
            for name in ("radial_hat", "azimuth_rad", "groove_offset_rad", "phase_roll_rad"):
                np.testing.assert_allclose(final_site[name], before_site[name], rtol=0, atol=1e-10)
    for before, final in zip(before_atoms.atoms, after_atoms.atoms, strict=True):
        before_xyz, final_xyz = [before.x, before.y, before.z], [final.x, final.y, final.z]
        if _key(before) != target:
            if before_xyz != final_xyz:
                raise ValueError("Native suffix affected atoms outside its declared base")
        else:
            np.testing.assert_allclose(final_xyz, np.asarray(before_xyz) + translation, rtol=0, atol=1e-10)
    assert prefix.model_dump_json() == captured
    return OrderedProbe(hashlib.sha256(captured.encode()).hexdigest(), suffix_entry.id, selected,
                        target, tuple(params["translation"]), before_records, before_atoms,
                        after_records, after_atoms, deepcopy(named_targets))
