import { versionedAssemblySourceKey } from '../api/assembly_instance_design_cache.js'

/** Preserve every authored input; only the live display representation is irrelevant.
 * Shared inline Designs are serialized once per snapshot, not once per instance.
 * The strings also retain the old values when a caller mutates a snapshot in place.
 */
export function captureAssemblyJointInputs(assembly) {
  const { instances = [], ...rest } = assembly ?? {}
  const values = [JSON.stringify(assembly == null ? null : rest)]
  const designs = new Map()
  let reusable = true
  for (const instance of instances) {
    const { representation: _representation, source, ...fields } = instance
    const { design, ...sourceFields } = source ?? {}
    const version = versionedAssemblySourceKey(instance)
    if (source?.type === 'file' ? !version
      : source?.type !== 'inline' || !design) reusable = false
    // The v2 response intentionally makes its live key non-enumerable.
    values.push(version, instance.geometrySourceKey)
    values.push(JSON.stringify({ ...fields, source: source == null ? source : sourceFields }))
    if (!designs.has(design)) designs.set(design, JSON.stringify(design))
    values.push(designs.get(design))
  }
  return { reusable, values }
}

export function sameAssemblyJointInputs(a, b) {
  return !!a && !!b && a.values.length === b.values.length
    && a.values.every((value, index) => value === b.values[index])
}

/** A ticket owns both the synchronous mesh pass and its async connector frames. */
export function initAssemblyJointRebuildGate({ eventTarget = globalThis.window } = {}) {
  let current = null, disposed = false
  const invalidate = () => { current = null }
  eventTarget?.addEventListener('nadoc:document-reset', invalidate)
  return {
    get disposed() { return disposed },
    begin(assembly, { force = false } = {}) {
      if (disposed) return null
      const inputs = captureAssemblyJointInputs(assembly)
      if (!force && inputs.reusable && sameAssemblyJointInputs(current?.inputs, inputs)) return null
      current = { inputs }
      return current
    },
    isCurrent(ticket, assembly) {
      return !disposed && ticket === current
        && sameAssemblyJointInputs(ticket.inputs, captureAssemblyJointInputs(assembly))
    },
    invalidate,
    dispose() {
      disposed = true
      invalidate()
      eventTarget?.removeEventListener('nadoc:document-reset', invalidate)
    },
  }
}
