/** PEG visualization math; coordinates are display-only nm in the fixed wall frame. */
export const isPegJob = job => ['peg_wall_qualification', 'peg_fast_relax'].includes(job?.run_kind)

/** Reconstruct each bonded chain across periodic faces, keeping its graft near the saved site. */
export function wholePegCoordinates(data, coordinates) {
  const xyz = coordinates.map(p => [...p]), peg = new Set(data.peg_indices)
  const neighbors = new Map([...peg].map(i => [i, []])), seen = new Set()
  for (const [a, b] of data.bonds) if (peg.has(a) && peg.has(b)) {
    neighbors.get(a).push(b); neighbors.get(b).push(a)
  }
  const near = (point, ref) => point.map((v, a) => v - Math.round((v-ref[a])/data.slit.box_nm[a])*data.slit.box_nm[a])
  for (const root of [...data.anchor_indices, ...peg]) {
    if (seen.has(root)) continue
    xyz[root] = near(xyz[root], data.coordinates_nm[root]); seen.add(root)
    const queue = [root]
    for (let n = 0; n < queue.length; n++) for (const i of neighbors.get(queue[n]) || []) {
      if (seen.has(i)) continue
      xyz[i] = near(xyz[i], xyz[queue[n]]); seen.add(i); queue.push(i)
    }
  }
  return xyz
}

/** Population RMSF about the mean; no rigid fit that would erase graft motion. */
export function pegRmsf(data, frames) {
  if (frames.length < 2) throw new Error('RMSF requires at least two recorded dynamics frames.')
  const mean = data.coordinates_nm.map(p => [...p]), m2 = mean.map(() => 0)
  data.peg_indices.forEach(i => { mean[i] = [0, 0, 0] })
  frames.forEach((frame, n) => {
    const xyz = wholePegCoordinates(data, frame.coordinates_nm)
    for (const i of data.peg_indices) for (let a = 0; a < 3; a++) {
      const delta = xyz[i][a] - mean[i][a]
      mean[i][a] += delta/(n+1); m2[i] += delta*(xyz[i][a]-mean[i][a])
    }
  })
  const angstrom = m2.map(v => 10*Math.sqrt(Math.max(0, v/frames.length)))
  return { mean, angstrom, max: Math.max(...data.peg_indices.map(i => angstrom[i])) }
}

/** Water oxygen selection uses periodic distances; no DNA/base lookup is involved. */
export function pegWaterIndices(data, xyz, shellAng = null) {
  const peg = new Set(data.peg_indices), result = [], radius2 = (shellAng/10)**2
  xyz.forEach((p, i) => {
    if (peg.has(i) || data.elements[i] !== 'O') return
    if (shellAng == null || data.peg_indices.some(j => xyz[j].reduce((d2, v, a) => {
      let d = v-p[a]; d -= Math.round(d/data.slit.box_nm[a])*data.slit.box_nm[a]
      return d2+d*d
    }, 0) <= radius2)) result.push(i)
  })
  return result
}
