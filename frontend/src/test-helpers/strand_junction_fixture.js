export function junctionFixture(forced = false) {
  const domains = [
    { helix_id: 'a', start_bp: 0, end_bp: 2, direction: 'FORWARD' },
    { helix_id: 'b', start_bp: 2, end_bp: 0, direction: 'REVERSE' },
  ]
  const strand = { id: 's', strand_type: 'staple', sequence: 'ACGGCA', domains }
  const design = { helices: [{ id: 'a' }, { id: 'b' }], strands: [strand],
    crossovers: [], forced_ligations: [] }
  if (forced) design.forced_ligations.push({ id: 'fl:1', extra_bases: 'ATTTTT',
    three_prime_helix_id: 'a', three_prime_bp: 2, three_prime_direction: 'FORWARD',
    five_prime_helix_id: 'b', five_prime_bp: 2, five_prime_direction: 'REVERSE' })
  else design.crossovers.push({ id: 'xo', extra_bases: 'ATTTTT',
    // Deliberately B→A: sequence still follows the strand, not the half order.
    half_b: { helix_id: 'a', index: 2, strand: 'FORWARD' },
    half_a: { helix_id: 'b', index: 2, strand: 'REVERSE' } })
  return { strand, design }
}
