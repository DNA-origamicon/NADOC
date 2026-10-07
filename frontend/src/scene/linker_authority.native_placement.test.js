// @vitest-environment node
import { describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
vi.mock('./ssdna_fjc.js', () => ({ fjcChainBetween: vi.fn(), isLoaded: () => false,
  ensureLoaded: async () => null, onLoaded: vi.fn() }))
import { assemblyConnectorArcEndpoints } from './assembly_connector_arcs.js'
import { initOverhangLinkArcs, resolveLinkerAttachAnchor } from './overhang_link_arcs.js'
import { lastPlacementFailure } from '../viewer/native_placement.js'

const anchors = () => [
  { overhang_id: 'oh_a', helix_id: 'h_a', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], is_five_prime: true },
  { overhang_id: 'oh_b', helix_id: 'h_b', bp_index: 0, direction: 'REVERSE', backbone_position: [4, 0, 0], is_five_prime: true },
]
const design = { strands: [], overhang_connections: [{ id: 'c', linker_type: 'ds',
  overhang_a_id: 'oh_a', overhang_b_id: 'oh_b', overhang_a_attach: 'free_end', overhang_b_attach: 'free_end',
  length_value: 2, length_unit: 'bp' }] }

describe('[native-placement] DS linker connector authority', () => {
  it('refuses a base-site substitute for an existing anchor backbone', () => {
    const n = anchors()[0]; n.base_position = [99, 99, 99]; delete n.backbone_position
    expect(() => resolveLinkerAttachAnchor([n], 'c', 'a', 'oh_a', 'free_end', 'ds'))
      .toThrow(/no base-site substitute/)
  })

  it('refuses a base-site substitute for an existing bridge boundary and draws no DS connector', () => {
    const geometry = anchors()
    geometry.push({ helix_id: '__lnk__c', bp_index: 0, direction: 'FORWARD', strand_id: '__lnk__c__a',
      domain_index: 1, copy_k: 2, base_position: [1, 2, 3] })
    const arcs = initOverhangLinkArcs(new THREE.Scene())
    try {
      expect(() => arcs.rebuild(design, geometry)).toThrow(/no base-site substitute/)
      expect(arcs.group.getObjectByName('overhangDsConnectorArcA')).toBeUndefined()
      expect(lastPlacementFailure().nucleotide_identity).toMatchObject({
        helix_id: '__lnk__c', bp_index: 0, strand_id: '__lnk__c__a', domain_index: 1, copy_k: 2,
      })
    } finally { arcs.dispose() }
  })

  it('defers connector geometry when bridge records have not arrived', () => {
    const arcs = initOverhangLinkArcs(new THREE.Scene())
    try {
      arcs.rebuild(design, anchors())
      expect(arcs.group.getObjectByName('overhangDsConnectorArcA')).toBeUndefined()
      expect(arcs.group.getObjectByName('overhangDsConnectorArcB')).toBeUndefined()
    } finally { arcs.dispose() }
  })

  it('rejects missing native DS backbone sites in assembly connectors too', () => {
    const strand = { id: '__lnk__c__a', domains: [{ helix_id: 'h_a', start_bp: 0, end_bp: 0 },
      { helix_id: '__lnk__c', start_bp: 0, end_bp: 1 }] }
    expect(() => assemblyConnectorArcEndpoints([strand], [{ strand_id: strand.id,
      helix_id: 'h_a', bp_index: 0, base_position: [0, 0, 0] }])).toThrow(/no base-site substitute/)
  })
})
