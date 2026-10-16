"""Memory-only Python -> JSON -> actual native Three.js display parity.

This checks the real wire boundary and renderer, without a browser, image golden,
GPU context, authored fixture files or changes to molecular calculations.
"""

import json
from pathlib import Path
import subprocess

import pytest

from backend.api.part_deformation_preview_dto import prepare_display
from tests.test_part_deformation_preview_dto import _component_input, _owned


NATIVE_DISPLAY_CHECK = r"""
import assert from 'node:assert/strict';
import * as THREE from './frontend/node_modules/three/build/three.module.js';
import { buildHelixObjects } from './frontend/src/scene/helix_renderer.js';
import { buildDeformationPreviewLayer } from './frontend/src/scene/part_dna_comparison_layer.js';
import { decodeDnaComparisonRecords } from './frontend/src/features/part_dna_comparison_codec.js';
import { _resetStapleColorPins } from './frontend/src/scene/helix_renderer/palette.js';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const packet = JSON.parse(input), original = JSON.stringify(packet);
const matrix = (mesh, id) => { const m = new THREE.Matrix4(); mesh.getMatrixAt(id, m); return m.elements; };
const summaries = [];
for (const component of [packet.before, packet.candidate]) {
  const scene = new THREE.Scene(), normalRoot = new THREE.Group(), token = Symbol('native parity');
  const preview = buildDeformationPreviewLayer(component, scene);
  const records = decodeDnaComparisonRecords(component.nucleotides);
  const axes = Object.fromEntries(component.helix_axes.map(a => [a.helix_id,
    { start: a.start, end: a.end, samples: a.samples, segments: a.segments, ovhgAxes: a.ovhg_axes ?? null }]));
  const native = buildHelixObjects(structuredClone(records),
    { ...structuredClone(component.display_topology), id: token }, normalRoot, {}, [], structuredClone(axes), 'full');
  native.setAxisShaftMode('deformed');
  const summary = [];
  for (const field of ['backboneEntries', 'slabEntries']) for (const entry of native[field]) {
    const displayed = preview.root.getObjectByName(entry.instMesh.name);
    assert.ok(displayed, 'native instance missing from preview');
    assert.deepEqual(matrix(displayed, entry.id), matrix(entry.instMesh, entry.id));
    summary.push(matrix(displayed, entry.id));
  }
  const axesIn = root => {
    const axes = [];
    root.traverse(node => { if (node.name === 'axisLine') axes.push({
      type: node.geometry.type, visible: node.visible, position: node.position.toArray(),
      quaternion: node.quaternion.toArray(), positions: [...node.geometry.attributes.position.array],
    }); });
    return axes;
  };
  assert.deepEqual(axesIn(preview.root), axesIn(normalRoot));
  summaries.push(summary);
  preview.dispose(); preview.dispose(); assert.equal(scene.children.length, 0);
  const geometries = new Set(), materials = new Set();
  normalRoot.traverse(node => {
    if (node._instanceAlpha && node.geometry?.getAttribute('instanceAlpha') === node._instanceAlpha)
      node.geometry.userData = { ...node.geometry.userData, shared: false };
    if (node.geometry && !node.geometry.userData.shared) geometries.add(node.geometry);
    for (const m of Array.isArray(node.material) ? node.material : [node.material]) if (m) materials.add(m);
    if (node.isInstancedMesh) node.dispose();
  });
  for (const g of geometries) g.dispose(); for (const m of materials) m.dispose();
  normalRoot.clear(); _resetStapleColorPins(token);
}
assert.equal(JSON.stringify(packet), original);
assert.notDeepEqual(summaries[0], summaries[1], 'deformation must remain visible in nucleotide matrices');
console.log('native-display-parity');
"""


@pytest.mark.parametrize("kind,grouped,scoped", [
    ("bend", False, False), ("bend", True, False), ("bend", False, True),
    ("twist", False, False), ("twist", True, False), ("twist", False, True),
])
def test_native_prepared_packet_preserves_rendered_matrices_and_curved_axes(kind, grouped, scoped):
    _check(prepare_display(*_owned(kind, grouped=grouped, scoped=scoped)))


def test_single_helix_twist_is_visible_in_actual_native_scene():
    _check(prepare_display(*_component_input("twist")))


def _check(packet):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", NATIVE_DISPLAY_CHECK],
        input=json.dumps(packet, allow_nan=False), text=True, capture_output=True,
        cwd=Path(__file__).resolve().parents[1], timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "native-display-parity"
