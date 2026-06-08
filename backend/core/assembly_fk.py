"""Pure forward-kinematics propagation over an Assembly's joint graph.

These helpers apply a world-space SE3 ``delta`` (a 4×4 numpy matrix) through the
kinematic joints of an :class:`~backend.core.models.Assembly`, mutating
:class:`~backend.core.models.PartInstance` transforms **in place**. They are
pure graph + matrix math over the core models — no HTTP, no file IO, no
``backend.api`` dependency — so the propagation rules are directly unit-testable
without a ``TestClient``.

Extracted verbatim from ``backend/api/assembly.py`` (the FK-helpers banner) so
the resolve / move / mate code paths keep their exact behavior; the api layer
imports these back under their original names (the ~50 call sites are unchanged).

Propagation model:
  * ``_fk_expand_rigid_group`` walks ``rigid`` joints bidirectionally — a rigid
    group moves as one body.
  * ``_fk_propagate`` walks the non-rigid kinematic children (parent → child),
    moving each child by ``delta`` and expanding its rigid group.
  * Both skip ``fixed`` instances (anchored) and anything already ``visited``.
"""

from __future__ import annotations

import numpy as np

from backend.core.models import Mat4x4


def _fk_apply_to_joint(joint, delta: np.ndarray) -> None:
    """Apply a world-space delta to a joint's axis_origin and axis_direction."""
    o = np.append(joint.axis_origin, 1.0)
    joint.axis_origin = (delta @ o)[:3].tolist()
    d = np.append(joint.axis_direction, 0.0)
    d_new = (delta @ d)[:3]
    norm = np.linalg.norm(d_new)
    joint.axis_direction = (d_new / norm if norm > 1e-9 else d_new).tolist()


def _build_inst_by_id(assembly) -> dict:
    """Build an id→PartInstance dict for O(1) lookups in FK propagation.

    With hundreds-to-thousands of instances, repeated linear scans
    (``next(i for i in assembly.instances if i.id == cid)``) dominate
    FK / resolve cost. Build this once at the top of each entry point and
    thread it through the BFS helpers.
    """
    return {i.id: i for i in assembly.instances}


def _fk_expand_rigid_group(assembly, instance_id: str, delta: np.ndarray,
                            visited: set, queue: list,
                            inst_by_id: dict | None = None) -> None:
    """BFS over rigid joints (bidirectional); apply delta to each new member."""
    if inst_by_id is None:
        inst_by_id = _build_inst_by_id(assembly)
    bfs = [instance_id]
    while bfs:
        cur = bfs.pop(0)
        for j in assembly.joints:
            if j.joint_type != 'rigid' or not j.instance_a_id or not j.instance_b_id:
                continue
            if j.instance_a_id == cur:
                nxt = j.instance_b_id
            elif j.instance_b_id == cur:
                nxt = j.instance_a_id
            else:
                continue
            if nxt in visited:
                continue
            m = inst_by_id.get(nxt)
            if not m or m.fixed:
                continue
            m.transform = Mat4x4.from_array(delta @ m.transform.to_array())
            if m.base_transform:
                m.base_transform = Mat4x4.from_array(delta @ m.base_transform.to_array())
            visited.add(nxt)
            queue.append(nxt)
            bfs.append(nxt)


def _fk_propagate(assembly, parent_ids: set, delta: np.ndarray, visited: set,
                   inst_by_id: dict | None = None) -> None:
    """BFS FK propagation from parent_ids through all non-rigid kinematic children."""
    if inst_by_id is None:
        inst_by_id = _build_inst_by_id(assembly)
    queue = list(parent_ids)
    while queue:
        pid = queue.pop(0)
        for j in assembly.joints:
            if j.instance_a_id != pid or j.joint_type == 'rigid':
                continue
            cid = j.instance_b_id
            if not cid or cid in visited:
                continue
            child = inst_by_id.get(cid)
            if not child or child.fixed:
                # Fixed child: do NOT update axis_origin — it must remain anchored at the
                # fixed child's connector, not drift with the parent's motion.
                continue
            _fk_apply_to_joint(j, delta)
            child.transform = Mat4x4.from_array(delta @ child.transform.to_array())
            if child.base_transform:
                child.base_transform = Mat4x4.from_array(delta @ child.base_transform.to_array())
            visited.add(cid)
            _fk_expand_rigid_group(assembly, cid, delta, visited, queue, inst_by_id)
            queue.append(cid)


def _move_instance_with_fk_delta(assembly, instance_id: str, delta: np.ndarray, visited: set,
                                   inst_by_id: dict | None = None) -> bool:
    if inst_by_id is None:
        inst_by_id = _build_inst_by_id(assembly)
    inst = inst_by_id.get(instance_id)
    if not inst or inst.fixed or instance_id in visited:
        return False
    inst.transform = Mat4x4.from_array(delta @ inst.transform.to_array())
    if inst.base_transform:
        inst.base_transform = Mat4x4.from_array(delta @ inst.base_transform.to_array())
    visited.add(instance_id)
    _fk_expand_rigid_group(assembly, instance_id, delta, visited, [], inst_by_id)
    _fk_propagate(assembly, {instance_id}, delta, visited, inst_by_id)
    return True
