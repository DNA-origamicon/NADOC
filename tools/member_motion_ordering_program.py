"""Bounded offline N → M → D experiment, not a production motion compiler.

M is a diagnostic exact-material world motion. D is an existing native composed
world rigid delta or saved-component edit of one base. Native prefix/suffix outputs
are captured once; changing M never reruns history. Reset/replacement remove only
the current saved pose lifetime, preserving authored fixed-world M. New material
and companion policy remain outside this admitted experiment.
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
    selected_material_keys: tuple[tuple, ...]
    target: tuple
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    pivot: tuple[float, float, float]
    suffix_mode: str
    replaced_pose_id: str | None
    _prefix_records: list
    _prefix_atoms: object
    _native_after_records: list
    _native_after_atoms: object
    _named_targets: list | None = None
    _component_free_records: list | None = None
    _component_free_atoms: object = None

    def evaluate(self, *, motion_enabled=True, motion=None):
        """Detached candidate only; no source model or command is published."""
        if not motion_enabled:
            # An absent diagnostic event retains the exact native suffix,
            # including float representations and native quaternion choices.
            return deepcopy(self._native_after_records), deepcopy(self._native_after_atoms), [
                {"feature_id": self.suffix_feature_id, "kind": self.suffix_mode,
                 "target": self.target, "native_output_exact": True}]
        motion = deepcopy(M if motion is None else motion)
        for name, size in (("rotation", 4), ("pivot", 3), ("translation", 3)):
            value = np.asarray(motion[name], dtype=float)
            if value.shape != (size,) or not np.all(np.isfinite(value)):
                raise ValueError(f"Expected finite {name} with {size} components")
        if not np.isclose(np.linalg.norm(motion["rotation"]), 1, rtol=0, atol=1e-8):
            raise ValueError("Expected unit motion quaternion")
        records = deepcopy(self._prefix_records)
        atoms = deepcopy(self._prefix_atoms)
        if self._component_free_records is not None:
            # Remove the current native pose lifetime before replaying fixed-world
            # M. This is component deletion, never inverse-N on displayed points.
            records = [deepcopy(base) if _key(row) == self.target else row
                       for row, base in zip(records, self._component_free_records, strict=True)]
            atoms.atoms = [deepcopy(base) if _key(atom) == self.target else atom
                           for atom, base in zip(atoms.atoms, self._component_free_atoms.atoms, strict=True)]
        selected = set(self.selected_material_keys)
        moved = [row for row in records if _key(row) in selected]
        for helix_id in self.selected_helix_ids:
            moved = _full_motion(moved, helix_id, pose=motion)
        moved_by_key = {_key(row): row for row in moved}
        records = [moved_by_key.get(_key(row), row) for row in records]
        for atom in atoms.atoms:
            if _key(atom) in selected:
                atom.x, atom.y, atom.z = _point([atom.x, atom.y, atom.z], motion)
        target_moved = self.target in selected
        if target_moved:
            pose = {"rotation": self.rotation, "pivot": self.pivot, "translation": self.translation}
            records = [_full_motion([record], self.target[0], pose=pose)[0]
                       if _key(record) == self.target else record for record in records]
            for atom in atoms.atoms:
                if _key(atom) == self.target:
                    atom.x, atom.y, atom.z = _point([atom.x, atom.y, atom.z], pose)
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
             "material_keys": list(self.selected_material_keys),
             "shared_helix_frame_policy": "unresolved; this probe outputs per-residue frames, not shared axes",
             "pose": deepcopy(motion), "frame": "world", "prefix_sha256": self.source_sha256},
            {"feature_id": self.suffix_feature_id, "kind": self.suffix_mode,
             "target": self.target, "translation": self.translation, "rotation": self.rotation,
             "pivot": self.pivot, "frame": "world",
             "replaced_pose_id": self.replaced_pose_id,
             "component_policy": "current saved pose lifetime; retain authored world-motion matrices",
             "after_event": "diagnostic-world-M"}]


def compile_ordered_probe(prefix, suffix_entry, selected_helix_ids, *, named_targets=None):
    """Admit one exact existing native suffix and a diagnostic selection union."""
    kind = suffix_entry.op_kind
    if kind not in {"nucleotide-transform", "nucleotide-transform-delete"}:
        raise ValueError("Only native single-nucleotide pose edits are admitted")
    params = deepcopy(suffix_entry.params)
    existing = None
    if kind == "nucleotide-transform-delete":
        existing = next((pose for pose in prefix.nucleotide_transforms
                         if pose.id == params["transform_id"]), None)
        if existing is None:
            raise ValueError("Reset does not address the current saved pose lifetime")
        target_params = existing.model_dump(mode="json")
        mode = "native-reset-component"
        pose = {"rotation": [0, 0, 0, 1], "pivot": [0, 0, 0], "translation": [0, 0, 0]}
    else:
        target_params = params
        mode = "native-compose-rigid" if params.get("compose") is True else "native-replace-component"
        pose = {name: params[name] for name in ("rotation", "pivot", "translation")}
    if target_params.get("kind") != "base" or target_params.get("copy_k", 0) != 0:
        raise ValueError("Only ordinary base pose components are admitted")
    target = target_params["helix_id"], target_params["bp_index"], target_params["direction"], 0
    if existing is None:
        existing = next((value for value in prefix.nucleotide_transforms
                         if (value.helix_id, value.bp_index, value.direction.value, value.copy_k) == target), None)
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
    after = commands.execute(kind, prefix.model_copy(deep=True), params)
    before_records, after_records = _geometry_for_design(prefix), _geometry_for_design(after)
    material = tuple(_key(row) for row in before_records if row["helix_id"] in selected)
    if named_targets is not None:
        material = existing_material_union(prefix, named_targets)
        if any(key[0] not in selected for key in material):
            raise ValueError("Named selection falls outside the declared helix envelope")
    if not material:
        raise ValueError("Selection contains no existing ordinary material")
    before_atoms, after_atoms = (build_atomistic_model(model, fast_bridges=True) for model in (prefix, after))
    if len(before_records) + len(before_atoms.atoms) > 65_536:
        raise ValueError("Offline ordering probe exceeds its fixed material budget")
    identity = [field.name for field in fields(Atom) if field.name not in {"x", "y", "z"}]
    if ([tuple(getattr(a, field) for field in identity) for a in before_atoms.atoms]
            != [tuple(getattr(a, field) for field in identity) for a in after_atoms.atoms]
            or before_atoms.bonds != after_atoms.bonds
            or [_key(r) for r in before_records] != [_key(r) for r in after_records]):
        raise ValueError("Native suffix changed material identity or topology; birth is not admitted")
    if target not in {_key(r) for r in before_records}:
        raise ValueError("Suffix target is absent from the compiled prefix")
    free_records = free_atoms = None
    check_records, check_atoms = before_records, before_atoms
    if mode != "native-compose-rigid" and existing is not None:
        component_free = commands.execute("nucleotide-transform-delete", prefix.model_copy(deep=True),
                                          {"transform_id": existing.id, "_proof_version": 1})
        free_records = _geometry_for_design(component_free)
        free_atoms = build_atomistic_model(component_free, fast_bridges=True)
        if ([tuple(getattr(a, field) for field in identity) for a in free_atoms.atoms]
                != [tuple(getattr(a, field) for field in identity) for a in before_atoms.atoms]
                or free_atoms.bonds != before_atoms.bonds
                or [_key(r) for r in free_records] != [_key(r) for r in before_records]):
            raise ValueError("Removing the current pose component changed material identity")
        for old, free in zip(before_records, free_records, strict=True):
            if _key(old) != target and old != free:
                raise ValueError("Component deletion affected an unselected Full record")
        for old, free in zip(before_atoms.atoms, free_atoms.atoms, strict=True):
            if _key(old) != target and old != free:
                raise ValueError("Component deletion affected an unselected atom")
        check_records, check_atoms = free_records, free_atoms
    rotation = Rotation.from_quat(pose["rotation"])
    for before, final in zip(check_records, after_records, strict=True):
        if _key(before) != target:
            if before != final:
                raise ValueError("Native suffix affected material outside its declared base")
        else:
            for name in ("backbone_position", "base_position", "slab_position"):
                np.testing.assert_allclose(final[name], _point(before[name], pose), rtol=0, atol=1e-10)
            for name in ("base_normal", "axis_tangent"):
                np.testing.assert_allclose(final[name], rotation.apply(before[name]), rtol=0, atol=1e-10)
            np.testing.assert_allclose(Rotation.from_quat(final["slab_quaternion"]).as_matrix(),
                                       (rotation * Rotation.from_quat(before["slab_quaternion"])).as_matrix(), rtol=0, atol=1e-10)
            before_site, final_site = before["helical_site"], final["helical_site"]
            np.testing.assert_allclose(final_site["axis_point"],
                                       _point(before_site["axis_point"], pose), rtol=0, atol=1e-10)
            np.testing.assert_allclose(final_site["radial_hat"], rotation.apply(before_site["radial_hat"]), rtol=0, atol=1e-10)
            for name in ("azimuth_rad", "groove_offset_rad", "phase_roll_rad"):
                np.testing.assert_allclose(final_site[name], before_site[name], rtol=0, atol=1e-10)
    for before, final in zip(check_atoms.atoms, after_atoms.atoms, strict=True):
        before_xyz, final_xyz = [before.x, before.y, before.z], [final.x, final.y, final.z]
        if _key(before) != target:
            if before_xyz != final_xyz:
                raise ValueError("Native suffix affected atoms outside its declared base")
        else:
            np.testing.assert_allclose(final_xyz, _point(before_xyz, pose), rtol=0, atol=1e-10)
    assert prefix.model_dump_json() == captured
    return OrderedProbe(hashlib.sha256(captured.encode()).hexdigest(), suffix_entry.id, selected, material,
                        target, tuple(pose["translation"]), tuple(pose["rotation"]), tuple(pose["pivot"]),
                        mode, existing.id if existing else None, before_records, before_atoms,
                        after_records, after_atoms, deepcopy(named_targets), free_records, free_atoms)
