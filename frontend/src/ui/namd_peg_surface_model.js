/** Native NAMD surface intent; never infer atom counts from statistical segments. */
export const NAMD_PEG_DEFAULTS = Object.freeze({
  name: 'PEG surface', material: 'hard_wall', normal_axis: '+z', position_nm: 0,
  shape: 'square', size_nm: 20, pore_diameter_nm: 0, layers: 1,
  density_per_nm2: .05, seed: 17, representation: 'atomistic', repeat_units: 36,
  segments: 8, end_groups: '', topology_reference: '', parameter_reference: '',
})
const NUMERIC = new Set(['position_nm', 'size_nm', 'pore_diameter_nm', 'layers',
  'density_per_nm2', 'seed', 'repeat_units', 'segments'])
export function namdPegFormSpec(form) {
  const result = {}
  for (const [key, fallback] of Object.entries(NAMD_PEG_DEFAULTS)) {
    const field = form.elements.namedItem(key)
    const raw = field && !field.disabled ? field.value : fallback
    if (NUMERIC.has(key) && (String(raw).trim() === '' || !Number.isFinite(Number(raw)))) {
      throw new Error('Enter a valid number for every surface and coating field.')
    }
    result[key] = NUMERIC.has(key) ? Number(raw) : String(raw).trim()
  }
  if (!result.name) throw new Error('Enter a surface name.')
  if (result.material === 'hard_wall') { result.pore_diameter_nm = 0; result.layers = 1 }
  if (result.pore_diameter_nm >= result.size_nm) throw new Error('Pore diameter must be smaller than the patch size.')
  const { chains } = namdPegEstimate(result)
  if (chains < 1) throw new Error('Increase patch size or density to request at least one chain.')
  if (chains > 10000) throw new Error('Surface drafts support at most 10,000 chains.')
  return result
}

export function namdPegEstimate(spec) {
  const pore = spec.material === 'graphene' ? spec.pore_diameter_nm : 0
  const area = spec.size_nm ** 2 * (spec.shape === 'circle' ? Math.PI / 4 : 1) - Math.PI * (pore / 2) ** 2
  return { area, chains: Math.floor(area * spec.density_per_nm2 + .5) }
}
