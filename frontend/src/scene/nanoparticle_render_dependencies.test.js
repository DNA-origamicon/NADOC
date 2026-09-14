import { expect, it } from 'vitest'
import { nanoparticleRenderInputsChanged as changed } from './nanoparticle_render_dependencies.js'

it('keeps coating resources on autosave but rebuilds for molecular and placement edits', () => {
  const original = {
    currentDesign: { metadata: { name: 'example' }, nanoparticles: [
      { id: 'gold', diameter_nm: 10, coating: { poses: [1] }, biotin_dna: [{ helix_id: 'dna' }] },
    ], nanoparticle_conjugations: [], nanoparticle_connection_versions: [], cluster_transforms: [] },
    currentGeometry: [{ helix_id: 'dna', backbone_position: [0, 1, 2] }],
  }
  const saved = structuredClone(original)
  saved.currentDesign.metadata.name = 'saved example'
  expect(changed(saved, original)).toBe(false)
  for (const edit of [
    s => { s.currentDesign.nanoparticles[0].coating.poses[0] = 2 },
    s => { s.currentDesign.nanoparticles[0].biotin_dna = [] },
    s => { s.currentDesign.nanoparticles = [] },
    s => { s.currentDesign.nanoparticle_connection_versions.push({ applied: true }) },
    s => { s.currentDesign.nanoparticle_conjugations.push({ spacer_nm: 2 }) },
    s => { s.currentDesign.cluster_transforms.push({ helix_ids: ['dna'] }) },
    s => { s.currentGeometry[0].backbone_position[0] = 3 },
  ]) {
    const next = structuredClone(original); edit(next)
    expect(changed(next, original)).toBe(true)
    expect(changed(original, next)).toBe(true) // undo
  }
})
