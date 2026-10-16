"""Full-source admission protects undo cost independently of replay evidence."""

from types import SimpleNamespace

import pytest

from backend.api.part_batch_publication_scope import admit_batch_source
from backend.api.part_recovery_budget import MAX_RECOVERY_BYTES
from backend.core.models import Annotation, Design, MinorMutationLogEntry, RoutingClusterLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_verification_capture import CaptureLimit
from tests.test_part_registered_batch import gold, prepare, request, source


def test_native_gold_and_grouped_mixed_recipe_are_admitted_without_replay():
    for body in (request(), request(gold())):
        candidate = prepare(body=body)["candidate"]
        admit_batch_source(candidate)
        candidate.annotations_enabled = False
        admit_batch_source(candidate)


@pytest.mark.parametrize("field,value", [
    ("repair_draft", object()), ("input_sources", {"unqualified": object()}),
    ("annotations", [Annotation(text="Retained annotation")]),
    ("atomistic_reference", object()), ("lattice_frames", [object()]),
    ("active_loadout_id", "simulation"), ("feature_log_cursor", 0),
])
def test_unqualified_retained_scope_refuses_without_visiting_payload(field, value):
    design = source()
    setattr(design, field, value)
    with pytest.raises(CommandContractError, match="Batch publication"):
        admit_batch_source(design)


def test_rootless_and_imported_basis_cannot_obtain_publication_scope():
    for design in (Design(), source().copy_with(recipe_root=source().recipe_root.model_copy(update={"kind": "import"}))):
        with pytest.raises(CommandContractError, match="explicit empty"):
            admit_batch_source(design)


def test_prospective_rows_include_every_new_routing_group_header():
    design = source()
    rows = [MinorMutationLogEntry(op_subtype="helix-add", label="Add helix", params={"_proof_version": 1}) for _ in range(61)]
    design.feature_log = [RoutingClusterLogEntry(children=rows)]  # 62 stored rows.
    admit_batch_source(design, [SimpleNamespace(kind="helix-add")])  # New group + child = 64.
    with pytest.raises(CommandContractError, match="64 history rows"):
        admit_batch_source(design, [SimpleNamespace(kind="helix-add"), SimpleNamespace(kind="strand-add")])
    with pytest.raises(CommandContractError, match="64 history rows"):
        admit_batch_source(design, [SimpleNamespace(kind="helix-add"), SimpleNamespace(kind="nanoparticle-create")])


@pytest.mark.parametrize("change", ["legacy", "different_family", "coating_marker"])
def test_unreviewed_history_is_not_promoted_by_kind_names(change):
    design = prepare(body=request(gold()))["candidate"]
    row = design.feature_log[0]
    if change == "legacy":
        row.params.pop("_proof_version")
    elif change == "different_family":
        row.op_kind = "protein-import"
    else:
        row.params["coating_version"] = 1
    with pytest.raises(CommandContractError, match="only native"):
        admit_batch_source(design)


def test_retained_payload_is_bounded_even_though_cold_replay_ignores_it():
    design = prepare(body=request(gold()))["candidate"]
    design.feature_log[0].post_state_gz_b64 = "x" * (MAX_RECOVERY_BYTES + 1)
    with pytest.raises(CaptureLimit, match="Retained recovery"):
        admit_batch_source(design)
