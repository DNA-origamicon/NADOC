"""Actual Python wire data consumed by the native JavaScript display adapter.

No browser, app, simulation, image or fixture artifacts. Parent serializes Node
with the other validation work. This checks cross-language transport and CPU
scene ownership; it does not qualify GPU behavior or visual appearance.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from backend.core.part_dna_comparison import project
from backend.core.design_geometry import _geometry_for_design
from tests.test_part_dna_comparison import small


def test_actual_native_packets_render_exact_source_frames_in_javascript():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual browser-language transport regression")
    kinds = ["straight", "loops", "tails", "reference", "bend", "twist", "sweep", "cluster",
             "child", "frame", "base_pose", "overhang", "subdomain", "crossover", "ligation", "periodic"]
    packets = []
    for kind in kinds:
        source = small(kind)
        packets.append({"kind": kind, "component": project(source), "design": source.model_dump(mode="json"),
                        "records": _geometry_for_design(source)})
    from tests.test_group_deformation_comparison import retained_tail
    for kind, source in zip(("named-selection", "historical-after-trim"), retained_tail()):
        kinds.append(kind)
        packets.append({"kind": kind, "component": project(source), "design": source.model_dump(mode="json"),
                        "records": _geometry_for_design(source)})
    program = r"""
import assert from 'node:assert/strict'
import fs from 'node:fs'
import * as THREE from './frontend/node_modules/three/build/three.module.js'
import { buildHelixObjects } from './frontend/src/scene/helix_renderer.js'
import { buildPartDnaComparisonLayer } from './frontend/src/scene/part_dna_comparison_layer.js'
import { decodeDnaComparisonRecords } from './frontend/src/features/part_dna_comparison_codec.js'
import { _resetStapleColorPins } from './frontend/src/scene/helix_renderer/palette.js'

const inputs = JSON.parse(fs.readFileSync(0, 'utf8')), outcomes = []
const values = root => { const nodes = []; root.traverse(n => { if (n.geometry) nodes.push(n) }); return nodes }
function release(root) {
  const nodes = values(root), geometries = new Set(), materials = new Set()
  for (const n of nodes) {
    if (!n.geometry.userData.shared || n._instanceAlpha) geometries.add(n.geometry)
    materials.add(n.material); if (n.isInstancedMesh) n.dispose()
  }
  for (const g of geometries) g.dispose()
  for (const m of materials) m.dispose()
  root.clear()
}
for (const packet of inputs) {
  const before = JSON.stringify(packet)
  assert.deepEqual(decodeDnaComparisonRecords(packet.component.nucleotides), packet.records)
  const scene = new THREE.Scene()
  if (['ligation', 'periodic'].includes(packet.kind)) {
    assert.throws(() => buildPartDnaComparisonLayer(packet.component, scene), /authored ligation/)
    assert.equal(scene.children.length, 0)
    outcomes.push({ kind: packet.kind, status: 'explicit_native_connection_refusal' })
    continue
  }
  const layer = buildPartDnaComparisonLayer(packet.component, scene)
  const normalScene = new THREE.Scene()
  const axes = Object.fromEntries(packet.component.helix_axes.map(a => [a.helix_id,
    { start: a.start, end: a.end, samples: a.samples, segments: a.segments, ovhgAxes: a.ovhg_axes ?? null }]))
  const native = buildHelixObjects(structuredClone(packet.records), packet.design, normalScene, {}, [], axes, 'full')
  try {
    for (const field of ['backboneEntries', 'slabEntries']) for (const entry of native[field]) {
      const mesh = values(layer.root).find(n => n.name === entry.instMesh.name)
      assert.ok(mesh, `${packet.kind}:${entry.instMesh.name}`)
      const actual = new THREE.Matrix4(), expected = new THREE.Matrix4()
      mesh.getMatrixAt(entry.id, actual); entry.instMesh.getMatrixAt(entry.id, expected)
      assert.deepEqual(actual.elements, expected.elements, `${packet.kind}:${field}:${entry.id}`)
    }
    assert.equal(JSON.stringify(packet), before)
    outcomes.push({ kind: packet.kind, status: 'exact_native_matrices', sites: packet.records.length })
  } finally {
    layer.dispose(); release(normalScene); _resetStapleColorPins(packet.design.id)
  }
}
process.stdout.write(JSON.stringify(outcomes))
"""
    result = subprocess.run([node, "--input-type=module", "-e", program],
                            input=json.dumps(packets), text=True, capture_output=True, timeout=20,
                            cwd=Path(__file__).resolve().parents[1], check=False)
    assert result.returncode == 0, result.stderr
    outcomes = json.loads(result.stdout)
    assert len(outcomes) == len(kinds)
    assert sum(row["status"] == "exact_native_matrices" for row in outcomes) == 16
