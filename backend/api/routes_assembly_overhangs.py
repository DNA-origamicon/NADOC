"""
API layer — assembly-level overhang binding + cross-part linker route handlers
(extracted from assembly.py).

Two cohesive cross-part overhang concerns share this router because they are one
reason to change (the Assembly→Overhangs Manager surface):

  * **AssemblyOverhangBinding** — a cross-part Watson-Crick pairing between two
    sub-domains on different ``PartInstance``s. Pure topology metadata; no
    geometry application.
  * **AssemblyOverhangConnection** — a cross-part linker (ss/ds, with an optional
    bridge sequence) that ALSO materialises linker topology (complement strands +
    a virtual ``__lnk__`` helix + bridge strand) onto the assembly so it renders
    in the 3D workspace. The ``relax`` endpoints rigid-place the free part so the
    connector arcs collapse (see ``backend/core/assembly_linker_relax.py``).

Routes
------
  POST   /assembly/overhang-bindings                              — create a WC binding
  PATCH  /assembly/overhang-bindings/{binding_id}                 — patch mode/wildcard
  DELETE /assembly/overhang-bindings/{binding_id}                 — remove a binding
  POST   /assembly/overhang-connections                           — create a cross-part linker
  PATCH  /assembly/overhang-connections/{connection_id}           — patch a linker
  DELETE /assembly/overhang-connections/{connection_id}           — remove a linker
  GET    /assembly/overhang-connections/{connection_id}/relax-status — gate the Relax button
  POST   /assembly/overhang-connections/{connection_id}/relax        — rigid-place relax
  GET    /assembly/duplexes                                        — list cross-part duplexes
  POST   /assembly/duplexes                                        — create (explicit register)
  POST   /assembly/duplexes/connect                                — producer (min-length register)
  POST   /assembly/duplexes/sync-from-bindings                     — derive from legacy bindings
  PATCH  /assembly/duplexes/{duplex_id}                            — edit register / driver / name
  DELETE /assembly/duplexes/{duplex_id}                            — remove a duplex
  GET    /assembly/duplexes/{duplex_id}/pairing                    — per-base classification
  GET    /assembly/overhangs/pairing-map                           — bp → paired/mismatch/toehold

Back-imports (B=7 — all shared kernel/infrastructure, zero bespoke): ``_assembly_response``
(shared kernel, the assembly-side twin of crud.py's ``_design_response``),
``_apply_assembly_mutation_with_feature_log`` (the assembly mutate + feature-log
wrapper), ``_find_instance`` (the shared instance lookup), the file-IO design-load
infra ``_assembly_source_path`` / ``_load_design_from_source`` (L4-blocked from
``backend/core`` — 20+ shared callers), ``_linker_geometry_for_assembly`` (the
L13 forced-shared emission helper — depends on api-layer ``crud._geometry_for_design``
so it cannot go to core, and is shared with the relax tests), and
``_propagate_fk_inplace`` (the shared FK-subtree mover). The kinematic/linker math
is imported from ``backend/core`` DIRECTLY (``_build_inst_by_id`` from
``assembly_fk``; the linker topology + relax fns from ``assembly_linker`` /
``assembly_linker_relax``), NOT back from the god-file. The six region-only helpers
(``_validate_overhang_ref``, ``_validate_overhang_in_instance``,
``_check_polarity_allowed``, ``_overhang_polarity``, ``_variant_id_for``,
``_find_assembly_connection``) and all five request models moved IN.

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import assembly_state
from backend.api.assembly import (
    _apply_assembly_mutation_with_feature_log,
    _assembly_response,
    _assembly_source_path,
    _find_instance,
    _linker_geometry_for_assembly,
    _load_design_from_source,
    _propagate_fk_inplace,
)
from backend.core.assembly_fk import _build_inst_by_id
from backend.core.models import Assembly, Vec3

router = APIRouter()


# ── Assembly-level overhang bindings ────────────────────────────────────────────


class CreateAssemblyOverhangBindingRequest(BaseModel):
    instance_a_id: str
    sub_domain_a_id: str
    overhang_a_id: str
    instance_b_id: str
    sub_domain_b_id: str
    overhang_b_id: str
    binding_mode: Optional[str] = None  # 'duplex' | 'toehold'
    allow_n_wildcard: Optional[bool] = None


class PatchAssemblyOverhangBindingRequest(BaseModel):
    binding_mode: Optional[str] = None
    allow_n_wildcard: Optional[bool] = None


def _validate_overhang_ref(
    design, sub_domain_id: str, overhang_id: str, side: str
) -> None:
    """Confirm ``sub_domain_id`` lives on overhang ``overhang_id`` in ``design``."""
    ovhg = next((o for o in design.overhangs if o.id == overhang_id), None)
    if ovhg is None:
        raise HTTPException(
            404, detail=f"Side {side}: overhang {overhang_id!r} not found."
        )
    if not any(sd.id == sub_domain_id for sd in (ovhg.sub_domains or [])):
        raise HTTPException(
            404,
            detail=f"Side {side}: sub-domain {sub_domain_id!r} not on overhang {overhang_id!r}.",
        )


@router.post("/assembly/overhang-bindings", status_code=200)
def create_assembly_overhang_binding(
    body: CreateAssemblyOverhangBindingRequest,
) -> dict:
    """Create a cross-part Watson-Crick binding between two overhangs."""
    from backend.core.models import AssemblyOverhangBinding

    assembly = assembly_state.get_or_404()
    inst_a = _find_instance(assembly, body.instance_a_id)
    inst_b = _find_instance(assembly, body.instance_b_id)
    design_a = _load_design_from_source(inst_a.source, _assembly_source_path(assembly))
    design_b = _load_design_from_source(inst_b.source, _assembly_source_path(assembly))
    _validate_overhang_ref(design_a, body.sub_domain_a_id, body.overhang_a_id, "A")
    _validate_overhang_ref(design_b, body.sub_domain_b_id, body.overhang_b_id, "B")

    # Reject duplicates: same unordered pair of (instance_id, sub_domain_id).
    key_new = frozenset(
        {
            (body.instance_a_id, body.sub_domain_a_id),
            (body.instance_b_id, body.sub_domain_b_id),
        }
    )
    if len(key_new) < 2:
        raise HTTPException(400, detail="Cannot bind a sub-domain to itself.")
    for ex in assembly.overhang_bindings:
        key_ex = frozenset(
            {
                (ex.instance_a_id, ex.sub_domain_a_id),
                (ex.instance_b_id, ex.sub_domain_b_id),
            }
        )
        if key_ex == key_new:
            raise HTTPException(409, detail=f"Binding already exists ({ex.name}).")

    next_n = len(assembly.overhang_bindings) + 1
    binding_kwargs: dict = dict(
        name=f"AB{next_n}",
        instance_a_id=body.instance_a_id,
        sub_domain_a_id=body.sub_domain_a_id,
        overhang_a_id=body.overhang_a_id,
        instance_b_id=body.instance_b_id,
        sub_domain_b_id=body.sub_domain_b_id,
        overhang_b_id=body.overhang_b_id,
    )
    if body.binding_mode is not None:
        binding_kwargs["binding_mode"] = body.binding_mode
    if body.allow_n_wildcard is not None:
        binding_kwargs["allow_n_wildcard"] = body.allow_n_wildcard
    new_binding = AssemblyOverhangBinding(**binding_kwargs)

    new_bindings = list(assembly.overhang_bindings) + [new_binding]
    mutated = assembly.model_copy(update={"overhang_bindings": new_bindings})

    oh_a_name = next(
        (o.label or o.id for o in design_a.overhangs if o.id == body.overhang_a_id),
        body.overhang_a_id,
    )
    oh_b_name = next(
        (o.label or o.id for o in design_b.overhangs if o.id == body.overhang_b_id),
        body.overhang_b_id,
    )
    label = f"{new_binding.name}: {inst_a.name}.{oh_a_name} ↔ {inst_b.name}.{oh_b_name}"

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-bind",
        label=label,
        params={
            **body.model_dump(mode="json"),
            "binding_id": new_binding.id,
            "name": new_binding.name,
        },
    )
    return _assembly_response(updated)


@router.patch("/assembly/overhang-bindings/{binding_id}", status_code=200)
def patch_assembly_overhang_binding(
    binding_id: str, body: PatchAssemblyOverhangBindingRequest
) -> dict:
    """Patch ``binding_mode`` or ``allow_n_wildcard`` on a cross-part binding."""
    assembly = assembly_state.get_or_404()
    bindings = list(assembly.overhang_bindings)
    idx = next((i for i, b in enumerate(bindings) if b.id == binding_id), -1)
    if idx < 0:
        raise HTTPException(
            404, detail=f"AssemblyOverhangBinding {binding_id!r} not found."
        )

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, detail="No fields to patch.")
    bindings[idx] = bindings[idx].model_copy(update=fields)
    mutated = assembly.model_copy(update={"overhang_bindings": bindings})

    changes = ", ".join(fields.keys())
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-bind-patch",
        label=f"{bindings[idx].name}: patch ({changes})",
        params={**fields, "binding_id": binding_id},
    )
    return _assembly_response(updated)


@router.delete("/assembly/overhang-bindings/{binding_id}", status_code=200)
def delete_assembly_overhang_binding(binding_id: str) -> dict:
    """Remove a cross-part overhang binding."""
    assembly = assembly_state.get_or_404()
    target = next((b for b in assembly.overhang_bindings if b.id == binding_id), None)
    if target is None:
        raise HTTPException(
            404, detail=f"AssemblyOverhangBinding {binding_id!r} not found."
        )
    new_bindings = [b for b in assembly.overhang_bindings if b.id != binding_id]
    mutated = assembly.model_copy(update={"overhang_bindings": new_bindings})

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-unbind",
        label=f"{target.name}: unbind",
        params={"binding_id": binding_id, "name": target.name},
    )
    return _assembly_response(updated)


# ── Assembly-level overhang connections (cross-part linkers) ────────────────────


class CreateAssemblyOverhangConnectionRequest(BaseModel):
    name: Optional[str] = None
    instance_a_id: str
    overhang_a_id: str
    overhang_a_attach: str  # 'root' | 'free_end'
    instance_b_id: str
    overhang_b_id: str
    overhang_b_attach: str
    linker_type: str  # 'ss' | 'ds'
    length_value: float
    length_unit: str  # 'bp' | 'nm'
    bridge_sequence: Optional[str] = None


class PatchAssemblyOverhangConnectionRequest(BaseModel):
    name: Optional[str] = None
    overhang_a_attach: Optional[str] = None
    overhang_b_attach: Optional[str] = None
    linker_type: Optional[str] = None
    length_value: Optional[float] = None
    length_unit: Optional[str] = None
    bridge_sequence: Optional[str] = None


class RelaxAssemblyLinkerRequest(BaseModel):
    """Body for the cross-part linker relax. Empty today (the placement is
    deterministic); kept for forward-compat (e.g. an explicit movable side)."""

    pass


def _validate_overhang_in_instance(design, overhang_id: str, side: str) -> None:
    if not any(o.id == overhang_id for o in (design.overhangs or [])):
        raise HTTPException(
            404, detail=f"Side {side}: overhang {overhang_id!r} not found."
        )


def _check_polarity_allowed(type_id: str, end_a: str, end_b: str) -> bool:
    """Mirror the frontend's _ctIsForbidden rule set, server-side.

    end_a / end_b are '5p' or '3p' (the overhang free-end polarity, derived
    from the overhang id suffix). Returns False (= forbidden) for the same
    combinations the frontend rejects so the two layers stay in sync.
    """
    # Derive from canonical type id.
    if type_id in ("end-to-root",):
        return end_a == end_b
    if type_id in ("root-to-root",):
        return end_a != end_b
    if type_id in ("root-to-root-dsdna-linker", "end-to-end-dsdna-linker"):
        return end_a == end_b
    if type_id in (
        "root-to-root-ssdna-linker",
        "end-to-end-ssdna-linker",
        "root-to-root-indirect",
        "end-to-end-indirect",
    ):
        return end_a != end_b
    if type_id in ("end-to-root-dsdna-linker", "root-to-end-dsdna-linker"):
        return end_a != end_b
    if type_id in ("end-to-root-ssdna-linker", "root-to-end-ssdna-linker"):
        return end_a == end_b
    return True


def _overhang_polarity(overhang_id: str) -> Optional[str]:
    """Recover '5p' / '3p' suffix from the canonical overhang id, e.g.
    ``ovhg_<helix>_<bp>_5p``. Returns None when no suffix is present."""
    if overhang_id.endswith("_5p"):
        return "5p"
    if overhang_id.endswith("_3p"):
        return "3p"
    return None


def _variant_id_for(linker_type: str, attach_a: str, attach_b: str) -> Optional[str]:
    """Reconstruct the CT variant id from (linker_type, attach_a, attach_b).

    Used only for server-side polarity rule lookup — mirrors the frontend's
    `_ctAttachPair` inverse plus the type family. Returns None for direct
    connections (which the assembly path does not create — those go through
    AssemblyOverhangBinding).
    """
    if linker_type not in ("ss", "ds"):
        return None
    family = "ssdna" if linker_type == "ss" else "dsdna"
    if attach_a == "free_end" and attach_b == "root":
        return f"end-to-root-{family}-linker"
    elif attach_a == "root" and attach_b == "free_end":
        return f"root-to-end-{family}-linker"
    elif attach_a == "root" and attach_b == "root":
        return f"root-to-root-{family}-linker"
    elif attach_a == "free_end" and attach_b == "free_end":
        return f"end-to-end-{family}-linker"
    return None


@router.post("/assembly/overhang-connections", status_code=200)
def create_assembly_overhang_connection(
    body: CreateAssemblyOverhangConnectionRequest,
) -> dict:
    """Create a cross-part linker between two overhangs on different parts."""
    from backend.core.models import AssemblyOverhangConnection

    if body.overhang_a_attach not in ("root", "free_end"):
        raise HTTPException(
            400,
            detail=f"overhang_a_attach must be 'root' or 'free_end' (got {body.overhang_a_attach!r}).",
        )
    if body.overhang_b_attach not in ("root", "free_end"):
        raise HTTPException(
            400,
            detail=f"overhang_b_attach must be 'root' or 'free_end' (got {body.overhang_b_attach!r}).",
        )
    if body.linker_type not in ("ss", "ds"):
        raise HTTPException(
            400, detail=f"linker_type must be 'ss' or 'ds' (got {body.linker_type!r})."
        )
    if body.length_unit not in ("bp", "nm"):
        raise HTTPException(
            400, detail=f"length_unit must be 'bp' or 'nm' (got {body.length_unit!r})."
        )
    # Allow 0 for indirect variants (shared-linker strand has no user-set length).
    if body.length_value < 0:
        raise HTTPException(400, detail="length_value must be non-negative.")

    assembly = assembly_state.get_or_404()
    inst_a = _find_instance(assembly, body.instance_a_id)
    inst_b = _find_instance(assembly, body.instance_b_id)
    design_a = _load_design_from_source(inst_a.source, _assembly_source_path(assembly))
    design_b = _load_design_from_source(inst_b.source, _assembly_source_path(assembly))
    _validate_overhang_in_instance(design_a, body.overhang_a_id, "A")
    _validate_overhang_in_instance(design_b, body.overhang_b_id, "B")

    # Polarity rule: reject combinations the frontend would mark forbidden,
    # so a misconfigured client can't sneak invalid linkers past the UI.
    pa = _overhang_polarity(body.overhang_a_id)
    pb = _overhang_polarity(body.overhang_b_id)
    variant = _variant_id_for(
        body.linker_type, body.overhang_a_attach, body.overhang_b_attach
    )
    if pa and pb and variant and not _check_polarity_allowed(variant, pa, pb):
        raise HTTPException(
            422,
            detail=f"Polarity {pa}/{pb} is forbidden for {variant} (server polarity rule).",
        )

    next_n = len(assembly.overhang_connections) + 1
    new_conn = AssemblyOverhangConnection(
        name=body.name or f"AL{next_n}",
        instance_a_id=body.instance_a_id,
        overhang_a_id=body.overhang_a_id,
        overhang_a_attach=body.overhang_a_attach,
        instance_b_id=body.instance_b_id,
        overhang_b_id=body.overhang_b_id,
        overhang_b_attach=body.overhang_b_attach,
        linker_type=body.linker_type,
        length_value=body.length_value,
        length_unit=body.length_unit,
        bridge_sequence=body.bridge_sequence,
    )
    new_list = list(assembly.overhang_connections) + [new_conn]

    # Materialise the cross-part linker topology (complement strands + virtual
    # __lnk__ helix + bridge strand) into the assembly so the linker is
    # visible in the 3D workspace and shows up as new rows in the strand
    # spreadsheet.
    from backend.core.assembly_linker import generate_assembly_linker_topology

    new_helices, new_strands = generate_assembly_linker_topology(
        new_conn,
        inst_a,
        inst_b,
        design_a,
        design_b,
    )
    mutated = assembly.model_copy(
        update={
            "overhang_connections": new_list,
            "assembly_helices": list(assembly.assembly_helices) + new_helices,
            "assembly_strands": list(assembly.assembly_strands) + new_strands,
        }
    )

    oh_a_name = next(
        (o.label or o.id for o in design_a.overhangs if o.id == body.overhang_a_id),
        body.overhang_a_id,
    )
    oh_b_name = next(
        (o.label or o.id for o in design_b.overhangs if o.id == body.overhang_b_id),
        body.overhang_b_id,
    )
    label = f"{new_conn.name}: {inst_a.name}.{oh_a_name} ↔ {inst_b.name}.{oh_b_name} ({body.linker_type}, {body.length_value:g} {body.length_unit})"

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-connection-add",
        label=label,
        params={
            **body.model_dump(mode="json"),
            "connection_id": new_conn.id,
            "name": new_conn.name,
        },
    )
    return _assembly_response(updated)


@router.patch("/assembly/overhang-connections/{connection_id}", status_code=200)
def patch_assembly_overhang_connection(
    connection_id: str, body: PatchAssemblyOverhangConnectionRequest
) -> dict:
    """Patch a cross-part overhang connection."""
    assembly = assembly_state.get_or_404()
    conns = list(assembly.overhang_connections)
    idx = next((i for i, c in enumerate(conns) if c.id == connection_id), -1)
    if idx < 0:
        raise HTTPException(
            404, detail=f"AssemblyOverhangConnection {connection_id!r} not found."
        )

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, detail="No fields to patch.")

    # Validate enum-like values when present.
    if fields.get("overhang_a_attach") not in (None, "root", "free_end"):
        raise HTTPException(
            400, detail="overhang_a_attach must be 'root' or 'free_end'."
        )
    if fields.get("overhang_b_attach") not in (None, "root", "free_end"):
        raise HTTPException(
            400, detail="overhang_b_attach must be 'root' or 'free_end'."
        )
    if fields.get("linker_type") not in (None, "ss", "ds"):
        raise HTTPException(400, detail="linker_type must be 'ss' or 'ds'.")
    if fields.get("length_unit") not in (None, "bp", "nm"):
        raise HTTPException(400, detail="length_unit must be 'bp' or 'nm'.")
    if (
        "length_value" in fields
        and fields["length_value"] is not None
        and fields["length_value"] < 0
    ):
        raise HTTPException(400, detail="length_value must be non-negative.")

    old_conn = conns[idx]
    new_conn = old_conn.model_copy(update=fields)
    conns[idx] = new_conn

    # Decide what to do with the linker topology depending on which fields
    # changed:
    #   length_value / length_unit / linker_type — regenerate from scratch.
    #   bridge_sequence (only) — keep topology, only recompose strand .sequence.
    #   anything else (attach, name) — leave the existing strands alone.
    topology_changing = {
        "length_value",
        "length_unit",
        "linker_type",
        "overhang_a_attach",
        "overhang_b_attach",
    }
    helices = list(assembly.assembly_helices)
    strands = list(assembly.assembly_strands)
    if any(f in fields for f in topology_changing):
        from backend.core.assembly_linker import (
            generate_assembly_linker_topology,
            remove_assembly_linker_topology,
        )

        helices, strands = remove_assembly_linker_topology(
            helices, strands, connection_id
        )
        inst_a = _find_instance(assembly, new_conn.instance_a_id)
        inst_b = _find_instance(assembly, new_conn.instance_b_id)
        design_a = _load_design_from_source(
            inst_a.source, _assembly_source_path(assembly)
        )
        design_b = _load_design_from_source(
            inst_b.source, _assembly_source_path(assembly)
        )
        add_h, add_s = generate_assembly_linker_topology(
            new_conn,
            inst_a,
            inst_b,
            design_a,
            design_b,
        )
        helices = helices + add_h
        strands = strands + add_s
    elif "bridge_sequence" in fields:
        from backend.core.assembly_linker import (
            recompose_strand_sequences_for_connection,
        )

        inst_a = _find_instance(assembly, new_conn.instance_a_id)
        inst_b = _find_instance(assembly, new_conn.instance_b_id)
        design_a = _load_design_from_source(
            inst_a.source, _assembly_source_path(assembly)
        )
        design_b = _load_design_from_source(
            inst_b.source, _assembly_source_path(assembly)
        )
        strands = recompose_strand_sequences_for_connection(
            new_conn,
            inst_a,
            inst_b,
            design_a,
            design_b,
            strands,
        )

    mutated = assembly.model_copy(
        update={
            "overhang_connections": conns,
            "assembly_helices": helices,
            "assembly_strands": strands,
        }
    )

    changes = ", ".join(fields.keys())
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-connection-patch",
        label=f"{conns[idx].name}: patch ({changes})",
        params={**fields, "connection_id": connection_id},
    )
    return _assembly_response(updated)


@router.delete("/assembly/overhang-connections/{connection_id}", status_code=200)
def delete_assembly_overhang_connection(connection_id: str) -> dict:
    """Remove a cross-part overhang connection."""
    assembly = assembly_state.get_or_404()
    target = next(
        (c for c in assembly.overhang_connections if c.id == connection_id), None
    )
    if target is None:
        raise HTTPException(
            404, detail=f"AssemblyOverhangConnection {connection_id!r} not found."
        )
    new_list = [c for c in assembly.overhang_connections if c.id != connection_id]

    from backend.core.assembly_linker import remove_assembly_linker_topology

    new_helices, new_strands = remove_assembly_linker_topology(
        list(assembly.assembly_helices),
        list(assembly.assembly_strands),
        connection_id,
    )
    mutated = assembly.model_copy(
        update={
            "overhang_connections": new_list,
            "assembly_helices": new_helices,
            "assembly_strands": new_strands,
        }
    )

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-connection-delete",
        label=f"{target.name}: delete linker",
        params={"connection_id": connection_id, "name": target.name},
    )
    return _assembly_response(updated)


def _find_assembly_connection(assembly: Assembly, connection_id: str):
    conn = next(
        (c for c in assembly.overhang_connections if c.id == connection_id), None
    )
    if conn is None:
        raise HTTPException(
            404, detail=f"AssemblyOverhangConnection {connection_id!r} not found."
        )
    return conn


@router.get(
    "/assembly/overhang-connections/{connection_id}/relax-status", status_code=200
)
def assembly_overhang_connection_relax_status(connection_id: str) -> dict:
    """Whether a cross-part linker can be rigid-place relaxed (gates the UI button)."""
    from backend.core.assembly_linker_relax import assembly_relax_status

    assembly = assembly_state.get_or_404()
    conn = _find_assembly_connection(assembly, connection_id)
    inst_a = _find_instance(assembly, conn.instance_a_id)
    inst_b = _find_instance(assembly, conn.instance_b_id)
    return assembly_relax_status(assembly, conn, inst_a, inst_b)


@router.post("/assembly/overhang-connections/{connection_id}/relax", status_code=200)
def relax_assembly_overhang_connection(
    connection_id: str,
    body: Optional[RelaxAssemblyLinkerRequest] = None,
) -> dict:
    """Rigidly move the free part so the ds linker becomes a coaxial native-length duplex.

    Holds one part fixed (per ``assembly_relax_status``) and rigid-places the
    other; then re-materializes the now-stale bridge from the moved world
    anchors. Single undoable feature-log entry.
    """
    from backend.core.assembly_linker_relax import (
        assembly_relax_status,
        relax_assembly_linker,
    )
    from backend.core.assembly_linker import (
        generate_assembly_linker_topology,
        remove_assembly_linker_topology,
    )

    assembly = assembly_state.get_or_404()
    conn = _find_assembly_connection(assembly, connection_id)
    inst_a = _find_instance(assembly, conn.instance_a_id)
    inst_b = _find_instance(assembly, conn.instance_b_id)
    design_a = _load_design_from_source(inst_a.source, _assembly_source_path(assembly))
    design_b = _load_design_from_source(inst_b.source, _assembly_source_path(assembly))

    status = assembly_relax_status(assembly, conn, inst_a, inst_b)
    if not status["available"]:
        raise HTTPException(400, detail=status["reason"])

    moved_id = status["movable_instance_id"]
    inst_moved = inst_a if moved_id == inst_a.id else inst_b

    # Zero-length INDIRECT ss linker: no bridge — a single complement↔complement
    # arc. Collapse it with ONE translation of the moved part. The indirect
    # strand topology is unchanged (its complement beads follow the moved part on
    # re-emission), so we only move the part and commit.
    if conn.length_value == 0:
        from backend.core.assembly_linker_relax import relax_assembly_indirect_linker

        nucs = _linker_geometry_for_assembly(assembly).get("nucleotides", [])
        try:
            new_T, info = relax_assembly_indirect_linker(
                conn,
                nucs,
                assembly.assembly_strands,
                inst_moved,
                movable_instance_id=moved_id,
                fixed_instance_id=status["fixed_instance_id"],
            )
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        working = assembly.model_copy(deep=True)
        inst_by_id = _build_inst_by_id(working)
        _propagate_fk_inplace(working, moved_id, new_T, inst_by_id)
        updated = _apply_assembly_mutation_with_feature_log(
            working,
            op_kind="assembly-overhang-connection-relax",
            label=f"{conn.name}: relax linker",
            params={"connection_id": connection_id, **info},
        )
        payload = _assembly_response(updated)
        payload["relax_info"] = info
        return payload

    bridge_helix_id = f"__lnk__{conn.id}"

    # Generate a fresh bridge from the CURRENT anchors and EMIT it (same pipeline
    # the renderer uses), so the relax minimizes the actual 3D backbone-bead
    # coordinates the user sees — not a re-derived approximation.
    base_h, base_s = remove_assembly_linker_topology(
        list(assembly.assembly_helices),
        list(assembly.assembly_strands),
        connection_id,
    )
    add_h, add_s = generate_assembly_linker_topology(
        conn, inst_a, inst_b, design_a, design_b
    )
    fresh = assembly.model_copy(
        update={
            "assembly_helices": base_h + add_h,
            "assembly_strands": base_s + add_s,
        }
    )
    nucs = _linker_geometry_for_assembly(fresh).get("nucleotides", [])

    moved_id = status["movable_instance_id"]
    inst_moved = inst_a if moved_id == inst_a.id else inst_b

    # Two-translation, rotation-free relax on the emitted beads. Returns the
    # moved part's pure translation + the bridge-helix translation (T1).
    try:
        new_T, t1, info = relax_assembly_linker(
            conn,
            nucs,
            fresh.assembly_strands,
            inst_moved,
            movable_instance_id=moved_id,
            fixed_instance_id=status["fixed_instance_id"],
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    # Work on a deep copy so the live assembly stays as the feature-log pre-state.
    working = assembly.model_copy(deep=True)
    inst_by_id = _build_inst_by_id(working)
    _propagate_fk_inplace(working, moved_id, new_T, inst_by_id)

    # Commit the fresh bridge with its __lnk__ helix slid onto the fixed overhang
    # (T1). Do NOT regenerate from the moved pose — that would re-center the
    # bridge and undo T1. The complement strands reference the parts' helices, so
    # they follow the (now-moved) parts on their own.
    t1v = np.asarray(t1, dtype=float)
    bridge_helices = []
    for h in add_h:
        if h.id == bridge_helix_id:
            ws = h.axis_start.to_array() + t1v
            we = h.axis_end.to_array() + t1v
            bridge_helices.append(
                h.model_copy(
                    update={
                        "axis_start": Vec3.from_array(ws),
                        "axis_end": Vec3.from_array(we),
                    }
                )
            )
        else:
            bridge_helices.append(h)
    helices, strands = remove_assembly_linker_topology(
        list(working.assembly_helices),
        list(working.assembly_strands),
        connection_id,
    )
    mutated = working.model_copy(
        update={
            "assembly_helices": helices + bridge_helices,
            "assembly_strands": strands + add_s,
        }
    )

    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-overhang-connection-relax",
        label=f"{conn.name}: relax linker",
        params={"connection_id": connection_id, **info},
    )
    payload = _assembly_response(updated)
    payload["relax_info"] = info
    return payload


# ── Cross-part AssemblyDuplex CRUD (Proposal-B convergence, Phase B) ─────────────
#
# The assembly-level analog of ``backend.api.routes_duplex`` — register-bearing
# hybridization edges between two overhangs on DIFFERENT PartInstances. Bindings are
# migrated to duplexes on load (``_derive_assembly_duplexes_if_empty`` in assembly.py);
# these routes let the UI create NEW cross-part duplexes, flip the driver, and delete
# them. Materialization into flattened topology is ``flatten_assembly``'s job
# (Phase D) — nothing here mutates a part's source design. See
# ``memory/project_assembly_overhang_bindings.md``.


class AssemblyDuplexEndBody(BaseModel):
    instance_id: str
    overhang_id: str
    start_bp: int
    end_bp: int


class CreateAssemblyDuplexBody(BaseModel):
    left: AssemblyDuplexEndBody
    right: AssemblyDuplexEndBody
    driver: str = "left"  # 'left' | 'right'
    bound: bool = False
    binding_mode: str = "duplex"  # 'duplex' | 'toehold'
    allow_n_wildcard: bool = True
    connection_type: Optional[str] = None


class ConnectAssemblyDuplexBody(BaseModel):
    instance_a_id: str
    overhang_a_id: str
    overhang_a_attach: str = "free_end"  # 'root' | 'free_end'
    instance_b_id: str
    overhang_b_id: str
    overhang_b_attach: str = "root"
    driver: Optional[str] = None  # None → longest-drives default
    allow_n_wildcard: bool = True


class PatchAssemblyDuplexBody(BaseModel):
    left: Optional[AssemblyDuplexEndBody] = None
    right: Optional[AssemblyDuplexEndBody] = None
    driver: Optional[str] = None
    bound: Optional[bool] = None
    name: Optional[str] = None


def _asm_duplex_end(body: AssemblyDuplexEndBody):
    from backend.core.models import AssemblyDuplexEnd

    return AssemblyDuplexEnd(
        instance_id=body.instance_id,
        overhang_id=body.overhang_id,
        start_bp=body.start_bp,
        end_bp=body.end_bp,
    )


def _find_assembly_duplex(assembly: Assembly, duplex_id: str):
    dx = next((d for d in assembly.duplexes if d.id == duplex_id), None)
    if dx is None:
        raise HTTPException(404, detail=f"AssemblyDuplex {duplex_id!r} not found.")
    return dx


def _validate_assembly_duplex_placement(
    assembly: Assembly, dx, *, ignore_id: Optional[str] = None
) -> None:
    """Pre-flight the HTTP-meaningful failures (404/422/409) so clients get typed
    codes instead of a 500 from the model validator. Cross-part mirror of
    ``routes_duplex._validate_placement``: resolves each end's backing domain from
    its OWN instance design, keeps the double-pairing 409 keyed on
    ``(instance_id, overhang_id)``, and the Watson-Crick gate."""
    from backend.core.assembly_duplex import (
        _instance_map,
        _resolve_end_context,
        assembly_duplex_wc_ok,
    )

    inst_map = _instance_map(assembly)

    # Claimed bp per (instance, overhang) from OTHER duplexes (double-pairing 409).
    claimed: dict = {}
    for other in assembly.duplexes:
        if other.id == ignore_id:
            continue
        for e in (other.left, other.right):
            claimed.setdefault((e.instance_id, e.overhang_id), set()).update(
                e.covered_bp()
            )

    for side, end in (("left", dx.left), ("right", dx.right)):
        _, dom = _resolve_end_context(
            assembly, inst_map, end.instance_id, end.overhang_id
        )
        if dom is None:
            raise HTTPException(
                404,
                detail=(
                    f"{side} overhang {end.overhang_id!r} on instance {end.instance_id!r} "
                    f"has no resolvable backing domain."
                ),
            )
        lo, hi = sorted((dom.start_bp, dom.end_bp))
        e_lo, e_hi = sorted((end.start_bp, end.end_bp))
        if e_lo < lo or e_hi > hi:
            raise HTTPException(
                422,
                detail=(
                    f"{side} bp interval [{end.start_bp}, {end.end_bp}] is outside "
                    f"overhang {end.overhang_id}'s backing domain [{lo}, {hi}]."
                ),
            )
        overlap = (
            claimed.get((end.instance_id, end.overhang_id), set()) & end.covered_bp()
        )
        if overlap:
            raise HTTPException(
                409,
                detail=(
                    f"bp {sorted(overlap)} on {end.instance_id}::{end.overhang_id} are already "
                    f"paired by another duplex (a base has at most one partner)."
                ),
            )

    ok, reason = assembly_duplex_wc_ok(assembly, dx)
    if not ok:
        raise HTTPException(
            422, detail=f"duplex register is not complementary: {reason}."
        )


@router.get("/assembly/duplexes", status_code=200)
def list_assembly_duplexes() -> dict:
    assembly = assembly_state.get_or_404()
    return {"duplexes": [d.model_dump() for d in assembly.duplexes]}


@router.post("/assembly/duplexes", status_code=200)
def create_assembly_duplex(body: CreateAssemblyDuplexBody) -> dict:
    """Create a cross-part duplex from an explicit register."""
    from backend.core.models import AssemblyDuplex
    from backend.core.assembly_duplex import smallest_unused_assembly_duplex_name
    from pydantic import ValidationError

    assembly = assembly_state.get_or_404()
    # Both instances must exist (typed 404 before touching the model).
    _find_instance(assembly, body.left.instance_id)
    _find_instance(assembly, body.right.instance_id)
    try:
        dx = AssemblyDuplex(
            name=smallest_unused_assembly_duplex_name(assembly),
            left=_asm_duplex_end(body.left),
            right=_asm_duplex_end(body.right),
            driver=body.driver,
            bound=body.bound,
            binding_mode=body.binding_mode,
            allow_n_wildcard=body.allow_n_wildcard,
            connection_type=body.connection_type,
        )
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    _validate_assembly_duplex_placement(assembly, dx)

    mutated = assembly.model_copy(update={"duplexes": [*assembly.duplexes, dx]})
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-duplex-add",
        label=f"{dx.name}: bind {dx.left.overhang_id} ↔ {dx.right.overhang_id}",
        params={**body.model_dump(mode="json"), "duplex_id": dx.id, "name": dx.name},
    )
    resp = _assembly_response(updated)
    resp["duplex_id"] = dx.id
    return resp


@router.post("/assembly/duplexes/connect", status_code=200)
def connect_assembly_duplex(body: ConnectAssemblyDuplexBody) -> dict:
    """Producer: create a cross-part duplex CONNECTING two overhangs at their attach
    ends. Register is computed mechanically (length = min, no resize — the longer
    overhang keeps its toehold; polarity inherited from the migration primitive).
    Idempotent per (instance, overhang) pair (409 if already connected)."""
    from backend.core.models import AssemblyDuplex
    from backend.core.assembly_duplex import (
        _instance_map,
        assembly_connect_register,
        assembly_longest_driver,
        smallest_unused_assembly_duplex_name,
    )
    from pydantic import ValidationError

    for attr in ("overhang_a_attach", "overhang_b_attach"):
        val = getattr(body, attr)
        if val not in ("root", "free_end"):
            raise HTTPException(
                400, detail=f"{attr} must be 'root' or 'free_end' (got {val!r})."
            )
    if body.driver is not None and body.driver not in ("left", "right"):
        raise HTTPException(400, detail="driver must be 'left' or 'right'.")

    assembly = assembly_state.get_or_404()
    _find_instance(assembly, body.instance_a_id)
    _find_instance(assembly, body.instance_b_id)

    pair_new = frozenset(
        {
            (body.instance_a_id, body.overhang_a_id),
            (body.instance_b_id, body.overhang_b_id),
        }
    )
    if len(pair_new) < 2:
        raise HTTPException(400, detail="Cannot connect an overhang to itself.")
    for dx in assembly.duplexes:
        pair_ex = frozenset(
            {
                (dx.left.instance_id, dx.left.overhang_id),
                (dx.right.instance_id, dx.right.overhang_id),
            }
        )
        if pair_ex == pair_new:
            raise HTTPException(
                409, detail="these overhangs are already connected by a duplex."
            )

    inst_map = _instance_map(assembly)
    try:
        left, right = assembly_connect_register(
            assembly,
            inst_map,
            body.instance_a_id,
            body.overhang_a_id,
            body.overhang_a_attach,
            body.instance_b_id,
            body.overhang_b_id,
            body.overhang_b_attach,
        )
    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    driver = body.driver or assembly_longest_driver(assembly, inst_map, left, right)
    try:
        dx = AssemblyDuplex(
            name=smallest_unused_assembly_duplex_name(assembly),
            left=left,
            right=right,
            driver=driver,
            allow_n_wildcard=body.allow_n_wildcard,
        )
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    _validate_assembly_duplex_placement(assembly, dx)

    mutated = assembly.model_copy(update={"duplexes": [*assembly.duplexes, dx]})
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-duplex-connect",
        label=f"{dx.name}: connect {dx.left.overhang_id} ↔ {dx.right.overhang_id}",
        params={**body.model_dump(mode="json"), "duplex_id": dx.id, "name": dx.name},
    )
    resp = _assembly_response(updated)
    resp["duplex_id"] = dx.id
    return resp


@router.post("/assembly/duplexes/sync-from-bindings", status_code=200)
def sync_assembly_duplexes() -> dict:
    """Ensure every legacy AssemblyOverhangBinding pair also has a display duplex
    (live equivalent of derive-on-load). Idempotent; a no-op returns the assembly
    unchanged without a feature-log entry."""
    from backend.core.assembly_duplex import sync_assembly_duplexes_from_bindings

    assembly = assembly_state.get_or_404()
    mutated = sync_assembly_duplexes_from_bindings(assembly)
    if len(mutated.duplexes) == len(assembly.duplexes):
        return _assembly_response(assembly)  # nothing new — no undo entry
    added = len(mutated.duplexes) - len(assembly.duplexes)
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-duplex-sync",
        label=f"Sync duplexes from bindings (+{added})",
        params={"added": added},
    )
    return _assembly_response(updated)


@router.patch("/assembly/duplexes/{duplex_id}", status_code=200)
def patch_assembly_duplex(duplex_id: str, body: PatchAssemblyDuplexBody) -> dict:
    """Edit a cross-part duplex's register / driver / bound flag / name. The driver
    persists on the duplex and is read by ``flatten_assembly`` at materialization —
    no live geometry is moved here (parts stay pristine until flatten)."""
    from pydantic import ValidationError

    assembly = assembly_state.get_or_404()
    current = _find_assembly_duplex(assembly, duplex_id)
    patch = body.model_dump(exclude_unset=True)

    update: dict = {}
    if "left" in patch and patch["left"] is not None:
        update["left"] = _asm_duplex_end(body.left)
    if "right" in patch and patch["right"] is not None:
        update["right"] = _asm_duplex_end(body.right)
    if "driver" in patch:
        if body.driver not in ("left", "right"):
            raise HTTPException(422, detail="driver must be 'left' or 'right'.")
        update["driver"] = body.driver
    if "bound" in patch:
        update["bound"] = body.bound
    if "name" in patch:
        new_name = (body.name or "").strip()
        if not new_name:
            raise HTTPException(422, detail="name must be non-empty.")
        update["name"] = new_name
    if not update:
        raise HTTPException(400, detail="No fields to patch.")

    try:
        candidate = current.model_copy(update=update, deep=True)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    if "left" in update or "right" in update:
        _validate_assembly_duplex_placement(assembly, candidate, ignore_id=duplex_id)

    new_list = [candidate if d.id == duplex_id else d for d in assembly.duplexes]
    mutated = assembly.model_copy(update={"duplexes": new_list})
    changes = ", ".join(update.keys())
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-duplex-patch",
        label=f"{candidate.name}: patch ({changes})",
        params={**patch, "duplex_id": duplex_id},
    )
    return _assembly_response(updated)


@router.delete("/assembly/duplexes/{duplex_id}", status_code=200)
def delete_assembly_duplex(duplex_id: str) -> dict:
    """Remove a cross-part duplex."""
    assembly = assembly_state.get_or_404()
    target = _find_assembly_duplex(assembly, duplex_id)
    new_list = [d for d in assembly.duplexes if d.id != duplex_id]
    mutated = assembly.model_copy(update={"duplexes": new_list})
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-duplex-delete",
        label=f"{target.name}: delete duplex",
        params={"duplex_id": duplex_id, "name": target.name},
    )
    return _assembly_response(updated)


@router.get("/assembly/duplexes/{duplex_id}/pairing", status_code=200)
def get_assembly_duplex_pairing(duplex_id: str) -> dict:
    from backend.core.assembly_duplex import classify_assembly_duplex

    assembly = assembly_state.get_or_404()
    dx = _find_assembly_duplex(assembly, duplex_id)
    return classify_assembly_duplex(assembly, dx)


@router.get("/assembly/overhangs/pairing-map", status_code=200)
def get_assembly_overhang_pairing_map(instance_id: str, overhang_id: str) -> dict:
    """bp → paired/mismatch/unpaired (toehold) coverage for one overhang on one
    instance, aggregating every AssemblyDuplex that touches it (multivalency)."""
    from backend.core.assembly_duplex import (
        _instance_map,
        _resolve_end_context,
        assembly_overhang_pairing_map,
    )

    assembly = assembly_state.get_or_404()
    _find_instance(assembly, instance_id)
    _, dom = _resolve_end_context(
        assembly, _instance_map(assembly), instance_id, overhang_id
    )
    if dom is None:
        raise HTTPException(
            404,
            detail=(
                f"Overhang {overhang_id!r} on instance {instance_id!r} has no resolvable "
                f"backing domain."
            ),
        )
    cov = assembly_overhang_pairing_map(assembly, instance_id, overhang_id)
    return {
        "instance_id": instance_id,
        "overhang_id": overhang_id,
        "pairing_map": {str(bp): st for bp, st in cov.items()},
    }
