"""Actual native display packets cross the Python/JavaScript boundary in memory."""

import json
from pathlib import Path
import subprocess

import pytest

from backend.core import models as m
from tests.test_part_transform_preview_dto import (
    cpd_source, dto, flexible_source, moved, small,
)
from tests.test_part_connection_application_commands import (
    application_prefix as application_prefix, _build, _params, _pending,
)
from tests.test_part_pending_connection_versions import native_prefix as native_prefix, append


SCRIPT = """
import { validateTransformPreviewDisplay } from './frontend/src/features/transform_preview_display.js';
import { buildTransformPreviewLayer } from './frontend/src/scene/transform_history_preview.js';
import { Scene } from './frontend/node_modules/three/build/three.module.js';
let raw = ''; for await (const chunk of process.stdin) raw += chunk;
const value = JSON.parse(raw);
const original = JSON.stringify(value);
validateTransformPreviewDisplay(value, { prepare: Object.hasOwn(value, 'before') });
const scene = new Scene();
const log = console.log;
try {
  console.log = () => {};
  for (const component of [value.before, value.candidate].filter(Boolean)) {
    const layer = buildTransformPreviewLayer(component, scene);
    try {
      if (!scene.children.includes(layer.root) || layer.geometry.records.length !== component.nucleotides.length)
        throw new Error('Native component was not completely adopted');
    } finally { layer.dispose(); }
  }
} finally { console.log = log; }
if (scene.children.length || JSON.stringify(value) !== original)
  throw new Error('Private renderer leaked resources or changed the received packet');
process.stdout.write('accepted');
"""


@pytest.mark.parametrize("variant", ["ordinary", "loops", "tails", "reference", "child", "frame",
    "overhang", "subdomain", "sweep", "extension", "modification", "cpd", "flexible", "ss", "ds", "duplex"])
def test_actual_complete_native_packet_is_accepted_by_frontend(variant, application_prefix):
    if variant == "cpd":
        source = cpd_source()
    elif variant == "flexible":
        source = flexible_source()
    elif variant in {"ss", "ds"}:
        pending = _pending(application_prefix.model_copy(deep=True), f"root-to-end-{variant}dna-linker")
        source, _ = _build(pending, _params(pending))
    elif variant == "duplex":
        first, second = application_prefix.overhangs[:2]
        source = append(application_prefix, "duplex-connect", {
            "_proof_version": 1, "history_seed": "212cb729-37fa-49e4-bb35-c6a0cbd2cd2e",
            "duplex_id": "display-duplex", "created_at": 4.0,
            "overhang_a_id": first.id, "overhang_b_id": second.id, "binding_ids": [],
        }, "display-duplex-connect")
    else:
        source = small(None if variant in {"ordinary", "extension", "modification"} else variant)
        if variant in {"extension", "modification"}:
            source.extensions = [m.StrandExtension(id="extension", strand_id="stap", end="three_prime",
                sequence="AT", modification="cy3" if variant == "modification" else None)]
    prefix, evaluated = moved(source)
    packet = dto().prepare_display(prefix, evaluated)
    assert_frontend(packet)


def assert_frontend(packet):
    result = subprocess.run(["node", "--input-type=module", "-e", SCRIPT],
        cwd=Path(__file__).resolve().parents[1], input=json.dumps(packet, allow_nan=False),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    # Native debug logging can bind its output method at module import. The
    # terminal marker is written only after every validation/cleanup assertion.
    assert result.stdout.splitlines()[-1] == "accepted"


@pytest.mark.parametrize("kind,extra", [("cluster_op", False), ("nucleotide-transform", False),
    ("nucleotide-transform-batch", False), ("nucleotide-transform-delete", False),
    ("nucleotide-transform", True), ("nucleotide-transform-batch", True),
    ("nucleotide-transform-delete", True)])
def test_actual_input_history_roles_render_exact_native_targets(kind, extra):
    from tests.test_part_transform_preview import FEATURE, owned_capture, service, source_recipe

    source = source_recipe(kind, extra=extra)
    prepared = service().prepare_from_capture(owned_capture(source), FEATURE)
    evaluated = service().evaluate(prepared, {})
    assert_frontend(dto().prepare_display(prepared.copy_prefix(), evaluated))


def test_explicit_upgrade_and_saved_compound_roles_cross_real_frontend_boundary():
    from tests.test_part_placement_pose_history import recipe, patch_from_prepare
    from tests.test_part_transform_preview import FEATURE, owned_capture, service

    source = recipe()
    prepared = service().prepare_from_capture(owned_capture(source), FEATURE)
    prefix = prepared.copy_prefix()
    original = next(row for row in source.feature_log if row.id == FEATURE)
    opened = dto().prepare_display(prefix, service().evaluate(prepared, {}), source_entry=original)
    assert_frontend(opened)
    upgraded = service().evaluate(prepared, patch_from_prepare(opened))
    # Prepare's context always belongs to the original row. Evaluate identifies
    # its candidate role separately while retaining the original lease role.
    packet = dto().evaluate_display(prefix, upgraded, source_entry=original)
    assert_frontend(packet)
    assert_frontend(dto().prepare_display(prefix, upgraded, source_entry=upgraded.entry))
