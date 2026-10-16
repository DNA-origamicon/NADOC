/** Closed display-only transport. Never accepted as a Design or a repair input. */
export const COMPARISON_SCOPE = 'uncoated-particles-free-proteins-v1'
const MAX_PLACEMENTS = 128, MAX_ATOMS = 4096, MAX_LEASE_SECONDS = 900
import { fail, finite, integer, text, shape, vector, list, unique } from './part_comparison_validation.js'
import { validateDnaComparisonComponent } from './part_dna_comparison_model.js'
export const DNA_COMPARISON_SCOPE = 'ordinary-dna-uncoated-particles-free-proteins-v2'
function rigidPose(values) {
  vector(values, 16)
  if (values.slice(12).some((value, index) => Math.abs(value - (index === 3 ? 1 : 0)) > 1e-9)) fail('nonrigid particle pose')
  for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) {
    let dot = 0
    for (let row = 0; row < 3; row++) dot += values[row * 4 + a] * values[row * 4 + b]
    if (Math.abs(dot - (a === b ? 1 : 0)) > 1e-7) fail('nonrigid particle pose')
  }
  const determinant = values[0] * (values[5] * values[10] - values[6] * values[9])
    - values[1] * (values[4] * values[10] - values[6] * values[8])
    + values[2] * (values[4] * values[9] - values[5] * values[8])
  if (Math.abs(determinant - 1) > 1e-7) fail('nonrigid particle pose')
}

export function validatePartComparisonPane(pane, { projectionVersion = 1 } = {}) {
  if (![1, 2].includes(projectionVersion)) fail('unsupported projection version')
  shape(pane, ['units', 'particles', 'proteins', 'bounds_nm', 'unplaced_asset_ids', ...(projectionVersion === 2 ? ['dna'] : [])])
  if (projectionVersion === 2) validateDnaComparisonComponent(pane.dna)
  if (pane.units !== 'nm') fail('unsupported coordinate units')
  list(pane.particles, MAX_PLACEMENTS); list(pane.proteins, MAX_PLACEMENTS)
  list(pane.unplaced_asset_ids, MAX_PLACEMENTS)
  if (pane.particles.length + pane.proteins.length > MAX_PLACEMENTS) fail('display placement allowance exceeded')
  unique(pane.particles); unique(pane.proteins); unique(pane.unplaced_asset_ids, value => value)
  for (const particle of pane.particles) {
    shape(particle, ['id', 'kind', 'diameter_nm', 'pose', 'authored_visible', 'display_color'])
    if (!['gold_nanosphere', 'quantum_dot'].includes(particle.kind)) fail('unsupported particle kind')
    if (!finite(particle.diameter_nm) || particle.diameter_nm <= 0 || particle.diameter_nm > 1000) fail('invalid particle diameter')
    rigidPose(particle.pose)
    if (typeof particle.authored_visible !== 'boolean') fail('missing authored visibility')
    if (typeof particle.display_color !== 'string' || !/^#[\da-f]{6}$/i.test(particle.display_color)) fail('unsupported particle display color')
  }
  let atomCount = 0
  for (const protein of pane.proteins) {
    shape(protein, ['id', 'asset_id', 'authored_visible', 'representation', 'atoms'])
    text(protein.asset_id)
    if (typeof protein.authored_visible !== 'boolean') fail('missing authored visibility')
    list(protein.atoms, MAX_ATOMS)
    atomCount += protein.atoms.length
    if (!protein.atoms.length || atomCount > MAX_ATOMS) fail('protein display atom allowance exceeded')
    let hasCA = false
    for (const atom of protein.atoms) {
      shape(atom, ['serial', 'helix_id', 'name', 'chain_id', 'x', 'y', 'z'])
      if (!Number.isSafeInteger(atom.serial) || atom.helix_id !== `__protein__${protein.id}`) fail('invalid protein atom reference')
      text(atom.name); text(atom.chain_id, 256, true)
      if (![atom.x, atom.y, atom.z].every(finite)) fail('nonfinite protein coordinates')
      hasCA ||= atom.name === 'CA'
    }
    if (protein.representation !== (hasCA ? 'trace' : 'ovoid')) fail('incomplete protein representation')
  }
  if (pane.bounds_nm === null) {
    if (pane.particles.length || pane.proteins.length || pane.dna?.bounds_nm) fail('missing display bounds')
  } else {
    shape(pane.bounds_nm, ['minimum', 'maximum'])
    vector(pane.bounds_nm.minimum, 3); vector(pane.bounds_nm.maximum, 3)
    if (pane.bounds_nm.minimum.some((value, index) => value > pane.bounds_nm.maximum[index])) fail('invalid display bounds')
  }
  return pane
}

export function validatePartComparisonEnvelope(value, binding) {
  shape(value, ['status', 'issues', 'projection_version', 'scope', 'comparison_basis', 'coverage',
    'published', 'proposed', 'job_id', 'design_id', 'source_revision', 'repair_draft', 'expires_in_seconds'])
  if (value.status !== 'projected' || ![1, 2].includes(value.projection_version)
      || value.projection_version !== (binding?.projectionVersion ?? 1)
      || value.scope !== (value.projection_version === 2 ? DNA_COMPARISON_SCOPE : COMPARISON_SCOPE)
      || value.comparison_basis !== 'published_materialized_authoring_vs_evaluated_recipe'
      || !Array.isArray(value.issues) || value.issues.length) fail('incomplete or unsupported projection')
  shape(value.repair_draft, ['draft_id', 'generation'])
  text(value.job_id); text(value.design_id); text(value.repair_draft.draft_id)
  if (!integer(value.source_revision) || !integer(value.repair_draft.generation)
      || value.job_id !== binding?.jobId || value.design_id !== binding.context?.designId
      || value.source_revision !== binding.context?.revision || value.repair_draft.draft_id !== binding.draftId
      || value.repair_draft.generation !== binding.generation) fail('response belongs to another evaluated proposal')
  if (!finite(value.expires_in_seconds) || value.expires_in_seconds <= 0 || value.expires_in_seconds > MAX_LEASE_SECONDS) fail('expired or invalid display lease')
  shape(value.coverage, ['complete', 'scientific_qualification', 'visibility', 'excluded_layers',
    ...(value.projection_version === 2 ? ['presentation_policy'] : [])])
  if (value.projection_version === 2 && value.coverage.presentation_policy !== 'all_authored_opaque_except_reference_strands') fail('unsupported DNA presentation policy')
  if (value.coverage.complete !== true || value.coverage.scientific_qualification !== false
      || value.coverage.visibility !== 'all_authored_placements'
      || !Array.isArray(value.coverage.excluded_layers) || value.coverage.excluded_layers.length !== 2
      || !['physical', 'presentation'].every(layer => value.coverage.excluded_layers.includes(layer))) fail('unsupported comparison basis')
  const options = { projectionVersion: value.projection_version }
  validatePartComparisonPane(value.published, options); validatePartComparisonPane(value.proposed, options)
  return value
}
