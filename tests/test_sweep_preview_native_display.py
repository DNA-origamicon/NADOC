"""Actual native Sweep packets cross the JavaScript display boundary in memory.

This is a wire-contract test, not a browser/GPU or visual qualification. No
candidate files, images, native scratch directories or stored fixtures exist.
"""

import json
from pathlib import Path
import subprocess

import pytest

from backend.api.part_sweep_preview_dto import evaluate_display, prepare_display
from tests.test_part_sweep_preview import prepared, service


CHECK = r"""
import assert from 'node:assert/strict';
import { validateSweepPreviewDisplay } from './src/features/sweep_preview_display.js';
let input = ''; for await (const chunk of process.stdin) input += chunk;
const { packets, detached, attached } = JSON.parse(input);
const original = JSON.stringify(packets);
for (const [index, packet] of packets.entries()) {
  assert.equal(validateSweepPreviewDisplay(packet, {
    prepare: index === 0, requireEnvelope: true,
  }), packet);
  assert.equal(packet.stage, 'feature');
  assert.equal(packet.source_equivalence_checked, false);
  assert.equal(packet.downstream_evaluated, false);
  assert.equal(packet.physical_validity, false);
  assert.equal(packet.sweep_preview.source_detached, index === 0 ? false : detached);
  assert.equal(packet.candidate === null, index === 2);
  assert.equal(typeof packet.sweep_preview.source_frame, 'object');
  assert.deepEqual(Object.keys(packet.sweep_preview.source_frame).sort(),
    ['axis_dir', 'frame_right', 'frame_up', 'grid_origin']);
  for (const value of Object.values(packet.sweep_preview.source_frame)) {
    assert.equal(value.length, 3);
    assert.ok(value.every(Number.isFinite));
  }
}
assert.equal(packets[0].control_context.inputs.source_helix_id !== null, attached);
assert.equal(JSON.stringify(packets), original, 'validator changed the native packet');
const malformed = structuredClone(packets[1]);
malformed.sweep_preview.source_frame = 0;
assert.throws(() => validateSweepPreviewDisplay(malformed, { prepare: false, requireEnvelope: true }));
process.stdout.write('native-sweep-wire-contract');
"""


@pytest.mark.parametrize("case", ["free", "attached-start", "attached-posed", "detached"])
def test_actual_prepare_and_geometry_on_off_packets_validate_without_reencoding(case):
    attached = case != "free"
    end = "start" if case == "attached-start" else "end"
    _, owner = prepared(attached=attached, end=end, posed=case == "attached-posed",
                        organized=case == "attached-posed")
    prefix = owner.copy_prefix()
    original = service().evaluate(owner, {})
    offset = 1 if case == "detached" else 0
    draft = {"points_nm": [[offset, 0, 0], [offset, 0, -5 if end == "start" else 5]]}
    evaluated = service().evaluate(owner, draft)
    envelope = {
        "preview_id": "9e9a3a9a-8908-4bb6-99eb-6ca98a4d192f",
        "lease_id": "985e13ee-6885-47dd-8394-12a639541e48",
        "expected_design_id": prefix.id, "expected_revision": 7,
        "feature_id": original.entry.id, "doc_id": "sweep-wire-test",
        "deformation_id": owner.deformation_id, "request_sequence": 0,
        "remaining_seconds": 55.0,
    }
    packets = [prepare_display(prefix, original, envelope=envelope)]
    for sequence, include_geometry in enumerate((True, False), start=1):
        packets.append(evaluate_display(prefix, evaluated, include_geometry=include_geometry,
            envelope={**envelope, "request_sequence": sequence}))
    result = subprocess.run(["node", "--input-type=module", "-e", CHECK],
        input=json.dumps({"packets": packets, "attached": attached,
                         "detached": case == "detached"}, allow_nan=False),
        text=True, capture_output=True, timeout=15, check=False,
        cwd=Path(__file__).resolve().parents[1] / "frontend")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "native-sweep-wire-contract"
