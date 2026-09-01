/**
 * Keep the backend's simulation Design synchronized with the assembly shown by
 * the frontend. Simulation engines intentionally share the existing Design job
 * APIs; assembly mode supplies that shared seam by materializing the complete
 * assembly into the same document's Design slot before an engine request.
 */

const SIMULATION_PREFIXES = [
  '/simulate',
  '/oxdna',
  '/lammps',
  '/mrdna',
  '/cando',
  '/snupi',
  '/blade',
  '/md',
  '/shape-metrics',
  '/benchmark',
  '/runpod',
]

export function isSimulationApiPath(path) {
  return SIMULATION_PREFIXES.some(prefix => path === prefix || path.startsWith(`${prefix}/`))
}

export function createAssemblySimulationContext() {
  let materializedKey = null
  let pendingKey = null
  let pending = null

  // Assembly editing commonly mutates the store object in place. Object identity
  // therefore cannot prove that the flattened simulation projection is current:
  // polymerize/add/transform can all leave `assembly === materializedAssembly` true.
  // A content key is cheap for the compact .nass manifest and makes every topology or
  // pose edit invalidate the shared simulation Design deterministically.
  const contentKey = (assembly) => {
    try { return JSON.stringify(assembly) }
    catch { return null }
  }

  async function ensure({ path, assemblyActive, assembly, materialize }) {
    if (!assemblyActive || !assembly || !isSimulationApiPath(path)) return false
    const key = contentKey(assembly)
    if (key !== null && key === materializedKey) return false
    if (pending && key !== null && key === pendingKey) {
      await pending
      return false
    }

    pendingKey = key
    pending = Promise.resolve().then(materialize)
    try {
      await pending
      materializedKey = key
      return true
    } finally {
      pending = null
      pendingKey = null
    }
  }

  function invalidate() {
    materializedKey = null
  }

  return { ensure, invalidate }
}
