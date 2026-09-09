import * as THREE from 'three'

// Visual adjacency only: these edges never enter a simulation topology. No
// periodic image edges are drawn across the cell. The cutoff excludes second
// neighbors (0.246 nm) and adjacent graphene layers (0.335 nm).
export function grapheneNeighbors(xyz, cutoff = 0.19) {
  const cells = new Map(), neighbors = Array.from({ length: xyz.length / 3 }, () => [])
  for (let i = 0; i < neighbors.length; i++) {
    const p = [0, 1, 2].map(k => Math.floor(xyz[3 * i + k] / cutoff))
    for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) {
      for (const j of cells.get(`${p[0] + x},${p[1] + y},${p[2] + z}`) || []) {
        const d2 = [0, 1, 2].reduce((sum, k) => sum + (xyz[3 * i + k] - xyz[3 * j + k]) ** 2, 0)
        if (d2 > 0.005 ** 2 && d2 < cutoff ** 2) { neighbors[i].push(j); neighbors[j].push(i) }
      }
    }
    const key = p.join(',')
    if (!cells.has(key)) cells.set(key, [])
    cells.get(key).push(i)
  }
  return neighbors
}

// Fill only complete carbon hexagons. This preserves the actual pore and sheet
// boundaries without guessing their position from a transformed MD frame.
export function grapheneTriangles(neighbors) {
  const indices = []
  for (let start = 0; start < neighbors.length; start++) {
    const path = [start]
    function walk(current) {
      if (path.length === 6) {
        if (neighbors[current].includes(start) && path[1] < current) {
          for (let k = 1; k < 5; k++) indices.push(start, path[k], path[k + 1])
        }
        return
      }
      for (const next of neighbors[current]) {
        if (next <= start || path.includes(next)) continue
        path.push(next); walk(next); path.pop()
      }
    }
    walk(start)
  }
  return indices
}

export function graphenePreviewSites(half, radius, layers, spacing) {
  const xyz = [], b = 0.142, dx = 3 * b, dy = Math.sqrt(3) * b
  for (let layer = 0; layer < layers; layer++) {
    for (let i = Math.floor(-half / dx); i <= Math.ceil(half / dx); i++) {
      for (let j = Math.floor(-half / dy); j <= Math.ceil(half / dy); j++) {
        for (const [u, v] of [[0, 0], [1 / 3, 0], [1 / 2, 1 / 2], [5 / 6, 1 / 2]]) {
          const x = (i + u) * dx, y = (j + v) * dy
          if (Math.abs(x) <= half && Math.abs(y) <= half && x * x + y * y >= radius * radius)
            xyz.push(x, y, -layer * spacing)
        }
      }
    }
  }
  return new Float32Array(xyz)
}

/** Retains visual adjacency between trajectory frames; coordinates update in place. */
export function initGrapheneRepresentation(scene) {
  let mesh = null, xyz = null, mode = 'ball', visible = true, neighbors = null
  const matrix = new THREE.Matrix4(), q = new THREE.Quaternion()
  const a = new THREE.Vector3(), b = new THREE.Vector3(), scale = new THREE.Vector3()
  const up = new THREE.Vector3(0, 1, 0)
  function release() {
    if (!mesh) return
    mesh.visible = false
    scene.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); mesh.dispose?.(); mesh = null
  }
  function draw() {
    if (!xyz?.length) { if (mesh) mesh.visible = false; return }
    if (mode !== 'ball' && !neighbors) neighbors = grapheneNeighbors(xyz)
    if (!mesh) {
      const material = new THREE.MeshStandardMaterial({ color: 0x4b5563, roughness: 0.55,
        side: THREE.DoubleSide, transparent: mode === 'plane', opacity: mode === 'plane' ? 0.72 : 1 })
      if (mode === 'plane') {
        const geometry = new THREE.BufferGeometry()
        geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(xyz.length), 3))
        geometry.setIndex(grapheneTriangles(neighbors))
        mesh = new THREE.Mesh(geometry, material)
      } else {
        const count = mode === 'ball' ? xyz.length / 3 : neighbors.reduce((n, row) => n + row.length, 0) / 2
        mesh = new THREE.InstancedMesh(mode === 'ball'
          ? new THREE.SphereGeometry(0.07, 8, 6) : new THREE.CylinderGeometry(0.025, 0.025, 1, 6), material, count)
      }
      mesh.name = 'Graphene nanopore'
      mesh.userData.solventKey = 'graphene'
      mesh.userData.grapheneRepresentation = mode
      mesh.frustumCulled = false
      scene.add(mesh)
    }
    mesh.visible = visible
    if (mode === 'plane') {
      mesh.geometry.attributes.position.array.set(xyz)
      mesh.geometry.attributes.position.needsUpdate = true
      mesh.geometry.computeVertexNormals()
    } else if (mode === 'ball') {
      for (let i = 0; i < xyz.length / 3; i++) {
        matrix.makeTranslation(xyz[3 * i], xyz[3 * i + 1], xyz[3 * i + 2]); mesh.setMatrixAt(i, matrix)
      }
      mesh.instanceMatrix.needsUpdate = true
    } else {
      let index = 0
      for (let i = 0; i < neighbors.length; i++) for (const j of neighbors[i]) {
        if (j <= i) continue
        a.fromArray(xyz, 3 * i); b.fromArray(xyz, 3 * j).sub(a)
        const length = b.length()
        q.setFromUnitVectors(up, b.clone().normalize())
        a.addScaledVector(b, 0.5); scale.set(1, length, 1)
        matrix.compose(a, q, scale); mesh.setMatrixAt(index++, matrix)
      }
      mesh.instanceMatrix.needsUpdate = true
    }
  }
  return {
    setFrame(points) {
      if (xyz?.length !== points?.length) { release(); neighbors = null }
      xyz = points; draw()
    },
    setDisplay(settings) {
      visible = settings.visible !== false
      const next = ['plane', 'ball', 'stick'].includes(settings.representation) ? settings.representation : mode
      if (next !== mode) { mode = next; release(); draw() }
      if (mesh) mesh.visible = visible && !!xyz?.length
    },
    clear() { xyz = null; neighbors = null; if (mesh) mesh.visible = false },
    dispose() { release(); xyz = null; neighbors = null },
    mesh: () => mesh,
  }
}
