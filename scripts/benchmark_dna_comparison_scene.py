#!/usr/bin/env python3
"""In-memory private DNA CPU scene timing; parent runs serially.

No browser/WebGL/app lifespan, disk artifacts or simulation. Actual native
projection packets feed the same JavaScript scene adapter used by the private
viewer. GPU allocation, appearance and user gestures remain separate gates.
Default timing uses natural garbage collection. --memory requests explicit GC
only for a separate retained-heap diagnostic; its timings are not qualification.
"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from backend.core.part_comparison_projection import compare
from scripts.benchmark_dna_comparison import native_recipe
from tests.test_part_dna_comparison import small


PROGRAM = r"""
import fs from 'node:fs'
import { performance } from 'node:perf_hooks'
import { buildPartComparisonScene } from './frontend/src/scene/part_comparison_viewer.js'

const input = JSON.parse(fs.readFileSync(0, 'utf8'))
if (input.memory && typeof global.gc !== 'function') throw new Error('Explicit GC is required for the memory diagnostic')
function inventory(panes) {
  const geometries = new Set(), materials = new Set(), buffers = new Set()
  let instances = 0, objects = 0
  for (const pane of panes) pane.scene.traverse(node => {
    objects++
    const privateAlpha = node._instanceAlpha && node.geometry?.getAttribute('instanceAlpha') === node._instanceAlpha
    if (node.geometry && (!node.geometry.userData.shared || privateAlpha)) geometries.add(node.geometry)
    for (const material of Array.isArray(node.material) ? node.material : [node.material]) if (material) materials.add(material)
    if (node.isInstancedMesh) {
      instances++
      for (const attribute of [node.instanceMatrix, node.instanceColor]) if (attribute?.array) buffers.add(attribute.array.buffer)
    }
  })
  for (const geometry of geometries) {
    for (const attribute of [...Object.values(geometry.attributes), geometry.index]) if (attribute?.array) buffers.add(attribute.array.buffer)
  }
  return { objects, owned_geometries: geometries.size, owned_materials: materials.size,
    instance_meshes: instances, owned_attribute_bytes: [...buffers].reduce((sum, buffer) => sum + buffer.byteLength, 0) }
}
const stats = values => {
  const sorted = [...values].sort((a, b) => a - b)
  return { count: values.length, p50_ms: sorted[Math.floor((sorted.length - 1) * .5)],
    p95_ms: sorted[Math.ceil((sorted.length - 1) * .95)], max_ms: sorted.at(-1) }
}
const cases = []
for (const entry of input.cases) {
  const original = JSON.stringify(entry.packet), samples = []
  for (let index = 0; index < input.repeats; index++) {
    if (input.memory) global.gc()
    const panes = [], options = { projectionVersion: 2, paletteToken: Symbol('CPU benchmark comparison') }
    const beforeHeap = process.memoryUsage().heapUsed, started = performance.now()
    let built, resources, cleaned, disposed
    try {
      panes.push(buildPartComparisonScene(entry.packet.published, options))
      panes.push(buildPartComparisonScene(entry.packet.proposed, options))
      built = performance.now() - started
      resources = inventory(panes)
    } finally {
      const closing = performance.now()
      for (const pane of panes) pane.dispose()
      disposed = performance.now() - closing
      cleaned = panes.every(pane => pane.scene.children.length === 0)
      panes.length = 0
    }
    if (input.memory) global.gc()
    const afterHeap = process.memoryUsage().heapUsed
    samples.push({ build_two_panes_ms: built, dispose_ms: disposed, ...resources,
      cleanup_verified: cleaned, input_unchanged: JSON.stringify(entry.packet) === original,
      heap_before_build_bytes: beforeHeap, heap_after_disposal_bytes: afterHeap,
      ...(input.memory ? { retained_heap_after_explicit_gc_delta_bytes: afterHeap - beforeHeap } : {}) })
  }
  cases.push({ case: entry.name, sites_per_pane: entry.packet.published.dna.nucleotides.length,
    build: stats(samples.map(s => s.build_two_panes_ms)), disposal: stats(samples.map(s => s.dispose_ms)), samples })
}
const passed = cases.every(c => c.samples.every(s => s.cleanup_verified && s.input_unchanged))
process.stdout.write(JSON.stringify({ scope: 'CPU construction/disposal only; no GPU, appearance, app or physical qualification',
  measurement_mode: input.memory ? 'explicit_gc_retention_diagnostic' : 'natural_gc_timing',
  timing_qualification_eligible: !input.memory,
  gc_policy: input.memory ? 'Explicit GC before construction and after disposal; timing results are diagnostic only'
    : 'Natural runtime GC; no explicit collection or GC-policy changes',
  explicit_gc_available: typeof global.gc === 'function', explicit_gc_requested: input.memory,
  heap_scope: input.memory ? 'V8 heap before construction and after disposal, both following requested collection; native/GPU allocations excluded'
    : 'V8 heap observations without collection; differences are not retained-memory measurements; native/GPU allocations excluded',
  rss_scope: 'Whole Node process high-water, including all cases and initialization; not incremental scene allocation',
  node_version: process.version, max_rss_kib: process.resourceUsage().maxRSS,
  cleanup_and_source_preservation: passed, cases }, null, 2))
process.exitCode = passed ? 0 : 1
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--memory", action="store_true",
                        help="Separate explicit-GC retained-heap diagnostic; timings are not qualification")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 9:
        parser.error("Use 1..9 repetitions")
    node = shutil.which("node")
    if node is None:
        parser.error("Node is required for the actual frontend CPU adapter")
    cases = []
    for name, source in [(kind, small(kind)) for kind in ("straight", "loops", "reference", "bend", "sweep", "overhang", "child")] + [
            ("uuid_1024_slots", native_recipe(512, 1)), ("uuid_six_helices", native_recipe(84, 6))]:
        cases.append({"name": name, "packet": compare(source, source.model_dump(mode="json"), projection_version=2)})
    arguments = [node, *(["--expose-gc"] if args.memory else []), "--input-type=module", "-e", PROGRAM]
    result = subprocess.run(arguments,
                            input=json.dumps({"repeats": args.repeats, "memory": args.memory, "cases": cases}, allow_nan=False),
                            text=True, capture_output=True, timeout=60,
                            cwd=Path(__file__).resolve().parents[1], check=False)
    if result.returncode:
        raise RuntimeError(result.stderr[:4096] or result.stdout[:4096])
    print(result.stdout)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
