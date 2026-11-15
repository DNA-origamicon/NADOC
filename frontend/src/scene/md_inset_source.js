/** Exact NAMD coordinates for insets, independent of the main representation.
 * Retains one topology and at most five selected-residue frames. */
import { makeAtomTable } from './atom_table.js'
import { atomBaseKey } from './base_ref.js'
import { cubicCoordinates } from './trajectory_interpolation.js'

export function insetAtomSubset(model, frame, keys) {
  const wanted = new Set(keys), table = makeAtomTable(model), atoms = []
  const offsets = frame?.dense ? new Map(Array.from(frame.serialMap, (serial, i) => [serial, i * 3])) : null
  for (let i = 0; i < table.count; i++) {
    const a = table.get(i), key = a.base_key || atomBaseKey(a)
    if (!wanted.has(key)) continue
    const offset = offsets ? offsets.get(a.serial) : a.serial * 3
    const xyz = frame === null ? [a.x, a.y, a.z] : frame?.dense ?? frame
    const positionOffset = frame === null ? 0 : offset
    if (positionOffset == null || !xyz || ![xyz[positionOffset], xyz[positionOffset + 1], xyz[positionOffset + 2]].every(Number.isFinite)) continue
    atoms.push({ ...table.materialize(i), base_key: key, x: xyz[positionOffset], y: xyz[positionOffset + 1], z: xyz[positionOffset + 2] })
  }
  const live = new Set(atoms.map(a => a.serial)), bonds = []
  const source = model.bonds ?? []
  if (ArrayBuffer.isView(source)) {
    for (let i = 0; i < source.length; i += 2) if (live.has(source[i]) && live.has(source[i + 1])) bonds.push([source[i], source[i + 1]])
  } else for (const [a, b] of source) if (live.has(a) && live.has(b)) bonds.push([a, b])
  return { atoms, bonds, element_meta: model.element_meta }
}

export function initMdInsetSource({ api, hub }) {
  let context = null, generation = 0, modelJob = null, modelPromise = null, busy = null, again = false
  let activeAbort = null
  const frames = new Map()
  const wanted = () => hub.residueKeys().length > 0
  const model = job => {
    if (modelJob !== job) { modelJob = job; modelPromise = api.getOxdnaAtomisticModel(job) }
    return modelPromise
  }
  function publish(data) {
    hub.publish(data.atoms.map(a => [a.base_key, a.name, a.x, a.y, a.z]), { exact: true, model: data })
  }
  async function load(c, index) {
    const key = JSON.stringify([c.job, c.stride, index, hub.residueKeys()])
    if (frames.has(key)) return frames.get(key)
    const token = generation
    const topology = await model(c.job)
    const response = await api.getOxdnaFramesAtomistic(c.job, [index], true, 'job', c.stride)
    const data = insetAtomSubset(topology, response?.[String(index)], hub.residueKeys())
    if (token === generation) {
      frames.set(key, data)
      while (frames.size > 5) frames.delete(frames.keys().next().value)
    }
    return data
  }
  async function refresh() {
    if (!context || !wanted()) return
    if (busy) { again = true; return busy }
    const c = context, token = generation
    const abort = activeAbort = new AbortController()
    hub.publish(null, { exact: true })
    busy = (async () => {
      let data
      if (c.kind === 'flex') {
        let r = c.reps?.atomistic_average
        let topology = c.reps?.atomistic_model
        // Never substitute a final mean for a preliminary map.
        if (!r && c.preliminary) return
        if (!r) r = await api.getOxdnaRmsfAtomistic(c.job, { frameRange: c.range, signal: abort.signal })
        topology ||= r?.model || await model(c.job)
        data = insetAtomSubset(topology, r?.atomistic, hub.residueKeys())
      } else data = await load(c, c.index)
      if (token === generation && c === context) publish(data)
    })().catch(() => { /* remain explicitly waiting; never synthesize coordinates */ }).finally(() => {
      busy = null
      if (again) { again = false; void refresh() }
    })
    return busy
  }
  hub.onRequest(() => { generation++; frames.clear(); void refresh() })
  return {
    flex(job, response, reps, range) {
      activeAbort?.abort()
      if (reps?.atomistic_model) { modelJob = job; modelPromise = Promise.resolve(reps.atomistic_model) }
      context = { kind: 'flex', job, preliminary: response.preliminary, reps, range }
      if (wanted()) hub.publish(null, { exact: true })
      generation++; return refresh()
    },
    frame(job, index, stride) {
      activeAbort?.abort()
      context = { kind: 'frame', job, index, stride }
      if (wanted()) hub.publish(null, { exact: true })
      generation++; return refresh()
    },
    async prepare(job, indices, stride) {
      if (!wanted()) return
      const c = { job, stride }
      for (const i of indices) await load(c, i)
    },
    interpolate(job, from, to, t, before, after, stride) {
      if (!wanted()) return
      const lookup = i => frames.get(JSON.stringify([job, stride, i, hub.residueKeys()]))
      const a = lookup(from), b = lookup(to)
      if (!a || !b) { hub.publish(null, { exact: true }); return }
      const packed = data => data ? Float64Array.from(data.atoms.flatMap(a => [a.x, a.y, a.z])) : null
      const xyz = cubicCoordinates(packed(lookup(before)), packed(a), packed(b), packed(lookup(after)), t)
      generation++; again = false; context = { kind: 'frame', job, index: t < .5 ? from : to, stride }
      publish({ ...a, atoms: a.atoms.map((atom, i) => ({ ...atom, x: xyz[i*3], y: xyz[i*3+1], z: xyz[i*3+2] })) })
    },
    clear() { activeAbort?.abort(); context = null; generation++; frames.clear(); modelJob = null; modelPromise = null; hub.clear() },
  }
}
