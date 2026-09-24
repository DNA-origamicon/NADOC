/**
 * Shared fixture for the hairpin/self-dimer checker tests: a design with two
 * single-overhang staples joined by an ss linker, and a report in the exact
 * shape `POST /design/hairpin-dimer-check` returns for it (values taken from a
 * real backend run of tests/test_hairpin_dimer.py's `_seed(linker_type="ss")`
 * at the default origami buffer: 0 mM Na⁺, 10 mM Mg²⁺, 200 nM).
 */

export const STRONG = 'GCGCGCGCTTTTGCGCGCGCTT'   // 8-bp GC stem + T4 loop
export const BENIGN = 'ACACACACACACACACACACAC'   // no Watson–Crick self-complement
const RC_STRONG = 'AAGCGCGCGCAAAAGCGCGCGC'
const RC_BENIGN = 'GTGTGTGTGTGTGTGTGTGTGT'

export const OA = 'ovhg_h_a_0_5p'
export const OB = 'ovhg_h_b_0_3p'
export const LINKER = '__lnk__c1__s'

export function makeDesign() {
  return {
    id: 'd1',
    helices: [{ id: 'h_a', loop_skips: [] }, { id: 'h_b', loop_skips: [] }, { id: '__lnk__c1', loop_skips: [] }],
    strands: [
      { id: 's_a', strand_type: 'staple', sequence: STRONG,
        domains: [{ helix_id: 'h_a', start_bp: 0, end_bp: 21, direction: 'FORWARD', overhang_id: OA }] },
      { id: 's_b', strand_type: 'staple', sequence: BENIGN,
        domains: [{ helix_id: 'h_b', start_bp: 0, end_bp: 21, direction: 'FORWARD', overhang_id: OB }] },
      { id: LINKER, strand_type: 'linker', sequence: null, domains: [
        { helix_id: 'h_a', start_bp: 21, end_bp: 0, direction: 'REVERSE', binds_overhang_id: OA },
        { helix_id: '__lnk__c1', start_bp: 0, end_bp: 5, direction: 'FORWARD' },
        { helix_id: 'h_b', start_bp: 21, end_bp: 0, direction: 'REVERSE', binds_overhang_id: OB },
      ] },
    ],
    overhangs: [
      { id: OA, label: 'OH-A', helix_id: 'h_a', strand_id: 's_a', sequence: STRONG,
        sub_domains: [{ id: 'sdA', start_bp_offset: 0, length_bp: 22 }] },
      { id: OB, label: 'OH-B', helix_id: 'h_b', strand_id: 's_b', sequence: BENIGN,
        sub_domains: [{ id: 'sdB', start_bp_offset: 0, length_bp: 22 }] },
    ],
    overhang_connections: [
      { id: 'c1', name: 'L1', overhang_a_id: OA, overhang_b_id: OB, linker_type: 'ss',
        length_value: 6, length_unit: 'bp', bridge_sequence: 'CCCAAA' },
    ],
    overhang_bindings: [],
    connection_versions: [],
    extensions: [],
  }
}

const HAIRPIN_A = {
  tm: 96.59, dg: -12.51, dh: -77.6, ds: -209.88, offset: 0,
  structure: ['////////----\\\\\\\\\\\\\\\\--', STRONG],
}
const DIMER_A = {
  tm: 67.84, dg: -25.23, dh: -164.4, ds: -448.72, offset: 0,
  structure: ['          TTTT        TT', '  GCGCGCGC    GCGCGCGC', '  CGCGCGCG    CGCGCGCG', 'TT        TTTT        --'],
}

export function makeReport({ scope = 'all' } = {}) {
  return {
    design_id: 'd1',
    scope,
    threshold_c: 30,
    severe_threshold_c: 50,
    conditions: { na_mM: 0, mg_mM: 10, dntp_mM: 0, conc_nM: 200, temp_c: 37 },
    method: 'primer3 thermodynamic alignment (nearest-neighbour)',
    checks: [
      { key: `overhang:${OA}`, kind: 'overhang', strand_id: 's_a', overhang_ids: [OA],
        sequence: STRONG, length: 22, status: 'checked', hairpin: HAIRPIN_A, dimer: DIMER_A,
        inputs: { overhangs: { [OA]: STRONG } }, max_tm: 96.59, flagged: true, severity: 'critical' },
      { key: `overhang:${OB}`, kind: 'overhang', strand_id: 's_b', overhang_ids: [OB],
        sequence: BENIGN, length: 22, status: 'checked', hairpin: null, dimer: null,
        inputs: { overhangs: { [OB]: BENIGN } }, max_tm: null, flagged: false, severity: null },
      { key: `linker:${LINKER}`, kind: 'linker', strand_id: LINKER, connection_id: 'c1',
        overhang_ids: [OA, OB], sequence: `${RC_STRONG}CCCAAA${RC_BENIGN}`, length: 50,
        status: 'checked',
        hairpin: {
          tm: 90.2, dg: -10.38, dh: -70.9, ds: -195.13, offset: 0,
          structure: ['--///////------\\\\\\\\\\\\\\----------------------------', `${RC_STRONG}CCCAAA${RC_BENIGN}`],
        },
        dimer: {
          tm: 70.35, dg: -26.19, dh: -163.0, ds: -441.12, offset: 0,
          structure: [
            '                          AA        AAAA        CCCAAAGTGTGTGTGTGTGTGTGTGTGT',
            '                            GCGCGCGC    GCGCGCGC',
            '                            CGCGCGCG    CGCGCGCG',
            'TGTGTGTGTGTGTGTGTGTGTGAAACCC        AAAA        AA--------------------------',
          ],
        },
        inputs: {
          overhangs: { [OA]: STRONG, [OB]: BENIGN },
          bridge: 'CCCAAA',
          domains: 'h_a:21:0:REVERSE|__lnk__c1:0:5:FORWARD|h_b:21:0:REVERSE',
        },
        max_tm: 90.2, flagged: true, severity: 'critical' },
    ],
    summary: { checked: 3, flagged: 2, critical: 2, unsequenced: 0 },
  }
}

/**
 * Amber-tier variant (30 < Tm ≤ 50 °C): overhang A's hairpin lowered to 42.5 °C
 * (the Tm primer3 gives ACGTAGCGTGTCTCCC at the origami buffer), no dimer, and
 * the linker dropped — same inputs, so every check stays current.
 */
export function makeWarningReport() {
  const r = makeReport()
  const a = r.checks[0]
  r.checks = [
    { ...a, hairpin: { ...a.hairpin, tm: 42.5, dg: -0.32 }, dimer: null, max_tm: 42.5, severity: 'warning' },
    r.checks[1],
  ]
  r.summary = { checked: 2, flagged: 1, critical: 0, unsequenced: 0 }
  return r
}
