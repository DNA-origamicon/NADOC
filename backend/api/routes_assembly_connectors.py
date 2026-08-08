"""
API layer — assembly instance-connector route handlers (extracted from assembly.py).

This module hosts the cohesive cluster of *instance connector* (InterfacePoint)
CRUD endpoints: add a named connector to a PartInstance, and remove one. They
were factored out of ``assembly.py`` following the same template as the other
assembly-side sub-routers (``routes_assembly_animations.py``,
``routes_assembly_configs.py``, ``routes_assembly_linkers.py``).

Routes
------
  POST   /assembly/instances/{instance_id}/connectors          — append an InterfacePoint
  DELETE /assembly/instances/{instance_id}/connectors/{label}  — remove an InterfacePoint

Three shared-infrastructure helpers are imported back from ``assembly.py``:
``_assembly_response`` (the assembly-side twin of crud.py's ``_design_response``;
the shared kernel), ``_apply_assembly_mutation_with_feature_log`` (the assembly
mutate + feature-log wrapper, the assembly twin of ``mutate_and_validate``), and
``_find_instance`` (the 1-line instance lookup used throughout). These are shared
kernel/infra, not bespoke entanglement.

URLs are unchanged from their previous home in assembly.py. Mounting is done
in ``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import assembly_state
from backend.api.assembly import (
    _apply_assembly_mutation_with_feature_log,
    _assembly_response,
    _find_instance,
)
from backend.core.models import ConnectionType, InterfacePoint, Vec3

router = APIRouter()


# ── Instance connectors (InterfacePoints) ─────────────────────────────────────


class AddConnectorRequest(BaseModel):
    label: Optional[str] = None
    position: list[float]
    normal: list[float]
    cluster_id: Optional[str] = None


@router.post("/assembly/instances/{instance_id}/connectors", status_code=201)
def add_connector(instance_id: str, body: AddConnectorRequest) -> dict:
    """Append an InterfacePoint (connector) to a PartInstance."""
    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)

    # Auto-label if not supplied
    existing = {ip.label for ip in inst.interface_points}
    label = body.label or next(
        f"C{i}" for i in range(1, 999) if f"C{i}" not in existing
    )
    if label in existing:
        raise HTTPException(
            400, detail=f"Connector label {label!r} already exists on this instance."
        )

    ip = InterfacePoint(
        label=label,
        position=Vec3(x=body.position[0], y=body.position[1], z=body.position[2]),
        normal=Vec3(x=body.normal[0], y=body.normal[1], z=body.normal[2]),
        connection_type=ConnectionType.COVALENT,
        cluster_id=body.cluster_id,
    )
    new_instances = [
        i.model_copy(update={"interface_points": [*i.interface_points, ip]})
        if i.id == instance_id
        else i
        for i in assembly.instances
    ]
    mutated = assembly.model_copy(update={"instances": new_instances})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-add-connector",
        label=f"Add connector {label} on {inst.name}",
        params={
            "instance_id": instance_id,
            "label": label,
            "position": list(body.position),
            "normal": list(body.normal),
            "cluster_id": body.cluster_id,
        },
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/instances/{instance_id}/connectors/{label}", status_code=200)
def delete_connector(instance_id: str, label: str) -> dict:
    """Remove a named InterfacePoint from a PartInstance."""
    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    if not any(ip.label == label for ip in inst.interface_points):
        raise HTTPException(
            404, detail=f"Connector {label!r} not found on instance {instance_id!r}."
        )
    new_instances = [
        i.model_copy(
            update={
                "interface_points": [
                    ip for ip in i.interface_points if ip.label != label
                ]
            }
        )
        if i.id == instance_id
        else i
        for i in assembly.instances
    ]
    mutated = assembly.model_copy(update={"instances": new_instances})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-connector",
        label=f"Delete connector {label} on {inst.name}",
        params={"instance_id": instance_id, "label": label},
    )
    return _assembly_response(assembly_state.get_or_404())
