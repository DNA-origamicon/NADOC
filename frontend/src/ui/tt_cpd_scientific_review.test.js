import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  focusBondStyle,
  reviewDecisionPayload,
  reviewScopeMessage,
  showTTCpdScientificReview,
} from './tt_cpd_scientific_review.js'

afterEach(() => { document.body.replaceChildren() })

describe('TT-CPD scientific review contracts', () => {
  it('makes product bonds visually distinct from ordinary model bonds', () => {
    expect(focusBondStyle('photoproduct_crosslink')).toMatchObject({ color: '#ff4fd8', label: 'new CPD crosslink' })
    expect(focusBondStyle('cyclobutane_ring')).toMatchObject({ color: '#d29922' })
    expect(focusBondStyle('terminal_cap')).toMatchObject({ color: '#3fb950' })
    expect(focusBondStyle('phosphate_boundary')).toMatchObject({ color: '#ffa657' })
    expect(focusBondStyle('ordinary').radius).toBeLessThan(focusBondStyle('photoproduct_crosslink').radius)
  })

  it('builds stable-key decisions and keeps revise out of fit partitions', () => {
    const scene = { product_id: 'tt-cpd-trans-syn-i', conformer_id: 'conformer-003' }
    expect(reviewDecisionPayload({
      stage: 'coupled_conformer', scene, decision: 'approve', reviewer: ' Jojo ',
      notes: ' preserved identity ', partition: 'validation',
    })).toEqual({
      stage: 'coupled_conformer', product_id: scene.product_id,
      conformer_id: scene.conformer_id, decision: 'approve', partition: 'validation',
      reviewer: 'Jojo', notes: 'preserved identity',
    })
    expect(reviewDecisionPayload({
      stage: 'coupled_conformer', scene, decision: 'revise', reviewer: 'Jojo',
      notes: 'change atom map', partition: 'training',
    }).partition).toBeNull()
  })

  it('states that visual approval is not force-field acceptance', () => {
    expect(reviewScopeMessage()).toContain('does not validate charges or force constants')
    expect(reviewScopeMessage()).toContain('enable NAMD')
  })

  it('makes stale geometry decisions visible and requires re-review', async () => {
    const scene = {
      product_id: 'tt-cpd-cis-syn-ii', model_id: 'model', atom_keys: ['1:C5'],
      elements: ['C'], coordinates_angstrom: [[0, 0, 0]], bonds: [],
      stereocenters: [], metadata: { stereochemistry: 'cis-syn-II' },
      decision: {
        decision: 'approve', reviewer: 'Jojo', notes: 'Old candidate geometry looked correct.',
        stale: true, stale_reason: 'The rendered definition geometry changed.',
      },
    }
    const api = {
      getPhotoproductScientificReview: vi.fn().mockResolvedValue({
        definition_scenes: [scene], conformer_groups: [],
      }),
      putPhotoproductScientificReviewDecision: vi.fn(),
    }
    const viewer = { setScene: vi.fn(), resetView: vi.fn(), setHideHydrogens: vi.fn(), dispose: vi.fn() }
    await showTTCpdScientificReview({ api, viewerFactory: () => viewer })
    expect(document.body.textContent).toContain('STALE APPROVE')
    expect(document.body.textContent).toContain('rendered definition geometry changed')
  })

  it('shows orbit-view review controls and records revise as gate-neutral', async () => {
    const scene = {
      product_id: 'tt-cpd-trans-syn-i', model_id: 'model', atom_keys: ['1:C5'],
      elements: ['C'], coordinates_angstrom: [[0, 0, 0]], bonds: [],
      stereocenters: [], metadata: { stereochemistry: 'trans-syn-I' }, decision: null,
    }
    const api = {
      getPhotoproductScientificReview: vi.fn().mockResolvedValue({
        definition_scenes: [scene], conformer_groups: [],
      }),
      putPhotoproductScientificReviewDecision: vi.fn().mockImplementation(async payload => ({
        simulation_ready: false, gate_effect: 'none', decision: { ...payload, reviewed_at: '2026-09-04T00:00:00Z' },
      })),
    }
    const viewer = { setScene: vi.fn(), resetView: vi.fn(), setHideHydrogens: vi.fn(), dispose: vi.fn() }
    await showTTCpdScientificReview({ api, viewerFactory: () => viewer })
    expect(document.body.textContent).toContain('Visual identity review only')
    expect(viewer.setScene).toHaveBeenCalledWith(scene)
    expect([...document.querySelectorAll('[data-review-decision]')].map(node => node.textContent)).toEqual(['Approve', 'Reject', 'Revise'])

    const fields = document.querySelectorAll('input, textarea')
    const reviewer = [...fields].find(node => node.placeholder === 'Reviewer name')
    const notes = [...fields].find(node => node.tagName === 'TEXTAREA')
    reviewer.value = 'Jojo'
    notes.value = 'The endpoint mapping needs a stereochemical revision.'
    document.querySelector('[data-review-decision="revise"]').click()
    await vi.waitFor(() => expect(api.putPhotoproductScientificReviewDecision).toHaveBeenCalled())
    expect(api.putPhotoproductScientificReviewDecision.mock.calls[0][0]).toMatchObject({
      decision: 'revise', partition: null, product_id: scene.product_id,
    })
    expect(document.body.textContent).toContain('remains unresolved and gate-blocking')
  })
})
