/** A populated design arriving before its separately-fetched geometry is not render-ready.
 * Releasing operation-idle waiters at that empty intermediate rebuild lets every job and
 * resource poll compete with the real geometry build. Empty designs legitimately finish. */
export function designRebuildAwaitingGeometry(design, geometry) {
  const hasRenderableDomains = (design?.strands || []).some(s => (s.domains || []).length > 0)
  return hasRenderableDomains && !(geometry?.length > 0)
}
