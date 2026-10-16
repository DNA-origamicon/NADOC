/** Live file versions supplied by /assembly; saved/inline keys lack a revision. */
export function versionedAssemblySourceKey(instance) {
  const key = instance?.geometrySourceKey
  return instance?.source?.type === 'file' && typeof key === 'string'
    && /^f:.*:\d+:[0-9a-f]*$/.test(key) ? key : null
}

/** Share base-source reads without borrowing overridden renderer Designs.
 * A file version survives placement/metadata changes. Legacy payloads are only
 * reusable within one instances snapshot; inline Designs are already available.
 */
export function initAssemblyInstanceDesignCache({ getContext, fetchDesign }) {
  let docId, assemblyId, instances, initialized = false, generation = 0
  let byId = new Map(), requests = new Map()

  function keyFor(instanceId, instance) {
    const version = versionedAssemblySourceKey(instance)
    if (version) return `version:${version}`
    const source = instance?.source
    return `snapshot:${generation}:${source?.type === 'file' ? `file:${source.path}` : `instance:${instanceId}`}`
  }

  function sync() {
    const context = getContext()
    const nextAssembly = context.assembly
    const nextInstances = nextAssembly?.instances
    if (!initialized || context.docId !== docId || nextAssembly?.id !== assemblyId) {
      requests = new Map()
      instances = undefined
      byId = new Map()
      initialized = true
      docId = context.docId
      assemblyId = nextAssembly?.id
      generation++
    }
    if (nextInstances !== instances) {
      instances = nextInstances
      generation++
      byId = new Map((instances ?? []).map(instance => [instance.id, instance]))
      const live = new Set([...byId].map(([id, instance]) => keyFor(id, instance)))
      for (const key of requests.keys()) if (!live.has(key)) requests.delete(key)
    }
    return context
  }

  async function get(instanceId) {
    const context = sync()
    const instance = byId.get(instanceId)
    if (context.assembly && !instance) return null
    if (instance?.source?.type === 'inline' && instance.source.design) {
      return { design: instance.source.design, instance_name: instance.name }
    }
    const key = keyFor(instanceId, instance)
    let request = requests.get(key)
    if (!request) {
      request = { promise: null }
      requests.set(key, request)
      request.promise = Promise.resolve().then(() => fetchDesign(instanceId, { docId: context.docId }))
        .then(result => {
          sync()
          if (requests.get(key) !== request) return null
          if (!result?.design) requests.delete(key)
          return result
        }, error => {
          if (requests.get(key) === request) requests.delete(key)
          throw error
        })
    }
    const result = await request.promise
    sync()
    const current = byId.get(instanceId)
    if (requests.get(key) !== request || keyFor(instanceId, current) !== key) return null
    return result?.design ? { ...result, instance_name: current?.name ?? result.instance_name } : null
  }

  return { get }
}
