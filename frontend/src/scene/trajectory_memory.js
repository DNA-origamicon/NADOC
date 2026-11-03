// One allowance per browser realm, shared by MD/oxDNA controllers and prepared
// clips. This bounds retained numerical payloads, not the browser's entire heap
// or renderer/GPU allocations. Transfers have a separate 128 MiB response cap.
export const TRAJECTORY_RETAINED_BYTES = 512 * 1024 * 1024
export const TRAJECTORY_RESPONSE_BYTES = 128 * 1024 * 1024

function storage(value, resources = new Map(), seen = new Set()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return resources
  seen.add(value)
  if (ArrayBuffer.isView(value)) resources.set(value.buffer, value.buffer.byteLength)
  else if (value instanceof ArrayBuffer) resources.set(value, value.byteLength)
  else if (Array.isArray(value) && value.every(v => typeof v === 'number')) resources.set(value, value.length * 8)
  else for (const item of value instanceof Map ? value.values() : Object.values(value)) storage(item, resources, seen)
  return resources
}

export function trajectoryStorageBytes(value) {
  return [...storage(value).values()].reduce((a, b) => a + b, 0)
}

export function createTrajectoryMemory(limitBytes = TRAJECTORY_RETAINED_BYTES) {
  const entries = new Map(), allocations = new Map()
  let bytes = 0, peakBytes = 0, evictions = 0
  function release(key, evict = false) {
    const entry = entries.get(key)
    if (!entry) return
    entries.delete(key)
    for (const [resource, size] of entry.resources) {
      const owners = allocations.get(resource) - 1
      if (owners) allocations.set(resource, owners)
      else { allocations.delete(resource); bytes -= size }
    }
    if (evict) { evictions++; entry.onEvict?.() }
  }
  function retain(key, value, onEvict, { pinned = false } = {}) {
    const resources = storage(value)
    const size = [...resources.values()].reduce((a, b) => a + b, 0)
    if (size > limitBytes) throw new Error('Trajectory payload exceeds the shared memory budget. Select a smaller range.')
    // Admission is atomic for pinned consumers (exports/full pages): a failed
    // replacement must leave the old payload charged and usable.
    const required = new Map(resources)
    for (const [old, entry] of entries) if (old !== key && entry.pinned) {
      for (const [resource, size] of entry.resources) required.set(resource, size)
    }
    if ([...required.values()].reduce((a, b) => a + b, 0) > limitBytes) throw new Error('Trajectory memory budget is in use. Close another trajectory or select a smaller range.')
    release(key)
    const additional = () => [...resources].reduce((n, [r, s]) => n + (allocations.has(r) ? 0 : s), 0)
    for (const [old, entry] of entries) {
      if (bytes + additional() <= limitBytes) break
      if (!entry.pinned) release(old, true)
    }
    if (bytes + additional() > limitBytes) throw new Error('Trajectory memory budget is in use. Close another trajectory or select a smaller range.')
    for (const [resource, size] of resources) {
      if (!allocations.has(resource)) bytes += size
      allocations.set(resource, (allocations.get(resource) || 0) + 1)
    }
    entries.set(key, { resources, onEvict, pinned })
    peakBytes = Math.max(peakBytes, bytes)
  }
  return { retain, release,
    touch(key) { const e = entries.get(key); if (e) { entries.delete(key); entries.set(key, e) } },
    stats: () => ({ bytes, peakBytes, limitBytes, entries: entries.size, evictions }),
  }
}

export const trajectoryMemory = createTrajectoryMemory()

let transferTail = null
export function queueTrajectoryTransfer(work) {
  let result
  try { result = transferTail ? transferTail.then(work, work) : Promise.resolve(work()) }
  catch (error) { result = Promise.reject(error) }
  const tail = result.then(() => {}, () => {})
  transferTail = tail
  void tail.then(() => { if (transferTail === tail) transferTail = null })
  return result
}

/** Eviction removes the actual owning reference, not just an accounting record. */
export class TrajectoryMemoryMap extends Map {
  constructor({ memory = trajectoryMemory, maxBytes = memory.stats().limitBytes, onEvict } = {}) {
    super(); this.memory = memory; this.maxBytes = maxBytes; this.onEvict = onEvict; this.leases = new Map()
  }
  get(key) { this.memory.touch(this.leases.get(key)); return super.get(key) }
  set(key, value) {
    if (trajectoryStorageBytes(value) > this.maxBytes) throw new Error('Trajectory frame exceeds the memory budget')
    this.delete(key)
    while (this.size && trajectoryStorageBytes([...this.values(), value]) > this.maxBytes) this.evict(this.keys().next().value)
    const lease = Symbol('trajectory frame')
    this.memory.retain(lease, value, () => { this.leases.delete(key); super.delete(key); this.onEvict?.(key) })
    this.leases.set(key, lease)
    super.set(key, value)
    return this
  }
  delete(key) { this.memory.release(this.leases.get(key)); this.leases.delete(key); return super.delete(key) }
  evict(key) { if (this.delete(key)) this.onEvict?.(key) }
  clear() { for (const key of this.keys()) this.delete(key) }
}
