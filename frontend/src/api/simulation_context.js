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
  '/design/oxdna',
  '/design/cando',
]

export function isSimulationApiPath(path) {
  path = path.split('?')[0]
  return SIMULATION_PREFIXES.some(prefix => path === prefix || path.startsWith(`${prefix}/`))
}

// Browsing a panel, polling a job, or stopping it must never build geometry.
// Other engine requests retain the existing preparation contract, including
// explicit previews, estimates, launches and result-to-design alignment.
export function needsAssemblySimulation(path, method = 'GET') {
  const route = path.split('?')[0]
  if (!isSimulationApiPath(route)) return false
  if (route.startsWith('/simulate/')) return false
  // FEM result/lifecycle endpoints use the immutable job snapshot.
  if (/^\/(cando|snupi)\/jobs\//.test(route)) return false
  if (route.startsWith('/runpod/') && !['/runpod/gpu-options', '/runpod/job-preview'].includes(route)) return false
  if (['/benchmark/hardware', '/md/queue', '/md/relax-presets', '/md/namd-available',
    '/md/gpu-status', '/md/optimize-advanced/hardware', '/md/run-dir-status', '/md/browse',
    '/md/peg-surfaces'].includes(route)) return false
  if (route.endsWith('/available')) return false
  if (method === 'GET' && /^\/(oxdna|lammps|mrdna|cando|snupi|blade|md)\/jobs(?:\/[^/]+(?:\/(progress|error-log|health|metrics|archive-status|download-status|trajectory-progress|export-progress))?)?$/.test(route)) return false
  if (/\/(stop|early-stop|cancel|archive|unarchive|finish-and-download)$/.test(route)) return false
  if (method === 'DELETE') return false
  return true
}

export function usesCompactSimulationProjection(path, method = 'GET') {
  return method === 'POST' && /^\/(cando|snupi)\/jobs$/.test(path.split('?')[0])
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

  async function ensure({ path, method = 'GET', assemblyActive, assembly, materialize }) {
    if (!assemblyActive || !assembly) {
      invalidate()
      return false
    }
    if (!needsAssemblySimulation(path, method)) return false
    const content = contentKey(assembly)
    const compact = usesCompactSimulationProjection(path, method)
    // A backend-only preparation cannot satisfy a later engine that still needs
    // the browser's full Design projection. Keep their cache entries distinct.
    const key = content === null ? null : `${compact ? 'compact' : 'full'}:${content}`
    if (key !== null && key === materializedKey) return false
    while (pending) {
      const same = key !== null && key === pendingKey
      await pending
      if (same) return false
      if (key !== null && key === materializedKey) return false
    }

    pendingKey = key
    pending = Promise.resolve().then(() => materialize({ compact }))
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
