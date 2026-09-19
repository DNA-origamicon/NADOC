/**
 * World-space bounding spheres for the selectable elements that have no backbone
 * beads — proteins and nanoparticles — so annotations can anchor, highlight and
 * route around them. Read-only; nothing is written back.
 *
 * Nanoparticle poses are read every call (cheap). A protein's extent scans its
 * atoms, so it is cached and refreshed on an interval (fast enough to follow a
 * gizmo drag, cheap enough to leave the frame budget alone).
 */
import { Vector3 } from 'three'

export const EXTERNAL_KINDS = new Set(['protein', 'nanoparticle'])
export const isExternalRef = ref => EXTERNAL_KINDS.has(ref?.kind)

const PROTEIN_REFRESH_MS = 120
/** Used only when a protein has no measurable extent (e.g. a single rendered atom). */
const MIN_PROTEIN_RADIUS_NM = 1

export function createExternalTargets({ getDesign, getProteinRenderer, getNanoparticleSubsystem, now = () => performance.now() }) {
  const proteinCache = new Map() // id → { at, design, sphere }

  function nanoparticle(id) {
    const design = getDesign()
    const particle = design?.nanoparticles?.find(p => p.id === id)
    const mesh = getNanoparticleSubsystem()?.meshes?.get(id)
    if (!particle || !mesh) return null
    const p = mesh.getWorldPosition(new Vector3())
    return { x: p.x, y: p.y, z: p.z, radius: particle.diameter_nm / 2 }
  }

  function protein(id) {
    const design = getDesign()
    if (!design?.protein_attachments?.some(a => a.id === id)) return null
    const cached = proteinCache.get(id)
    const t = now()
    if (cached && cached.design === design && t - cached.at < PROTEIN_REFRESH_MS) return cached.sphere
    const extent = getProteinRenderer()?.extentOf?.(a => a.helix_id === `__protein__${id}`) ?? null
    const sphere = extent ? { ...extent, radius: Math.max(extent.radius, MIN_PROTEIN_RADIUS_NM) } : null
    proteinCache.set(id, { at: t, design, sphere })
    return sphere
  }

  const resolve = ref => (ref?.kind === 'nanoparticle' ? nanoparticle(ref.id) : ref?.kind === 'protein' ? protein(ref.id) : null)

  return {
    resolve,
    /** Every protein and nanoparticle, for placement to route callouts around. */
    listAll() {
      const design = getDesign()
      const out = []
      for (const p of design?.nanoparticles ?? []) { const s = nanoparticle(p.id); if (s) out.push(s) }
      for (const a of design?.protein_attachments ?? []) { const s = protein(a.id); if (s) out.push(s) }
      return out
    },
  }
}
