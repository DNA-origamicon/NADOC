import { afterEach, expect, it, vi } from 'vitest'

const { viewers } = vi.hoisted(() => ({ viewers: [] }))
vi.mock('./geometry_review_viewer.js', () => ({ createAttachmentReviewViewer: () => {
  const view = { controls: { addEventListener: vi.fn(), update: vi.fn() }, focusAtoms: vi.fn(),
    fit: vi.fn(), setRepresentation: vi.fn(), dispose: vi.fn(), isRendered: () => true }
  viewers.push(view); return view
} }))
vi.mock('./molecular_placement_audit.js', () => ({ auditStrandColorMap: () => new Map(),
  auditDefectRows: () => [{ text: 'Current PIERCING: exact bond and ring' }], copyAuditCameraState: vi.fn() }))
import { mountGeometryReview } from './corner_placement_review.js'

afterEach(() => { document.body.replaceChildren(); viewers.length = 0 })

it('explains the isolated proposal, shows every junction and preserves focus/representation controls', () => {
  const host = document.createElement('div'); document.body.append(host)
  const metrics = { max_covalent_nm: .19, clashes: 0, piercings: 0 }
  const model = { diagnostics: { n_clashes: 0, clash_threshold_nm: .08, piercing: { n_pierced: 0 }, max_junction_covalent_nm: .19 } }
  const evidence = { label: 'Corner — 2HB', current: model, candidate: model,
    displacement: { n_displaced: 50 }, construction: ['F1: Extrude 1'], candidate_process: ['Separate candidate evaluation'],
    limitations: ['No production promotion'], junctions: [{ label: 'Helix 0:42 → helix 2:45',
      insert_bases: 3, atom_serials: [1, 2, 3], max_displacement_nm: .8, current: metrics, candidate: metrics }],
    phase_sweep: { cases: [{ candidate_invalid_atoms: 0, candidate_clashes: 0, candidate_piercings: 0,
      candidate_max_covalent_nm: .19, current_invalid_atoms: 4 }] } }
  const review = mountGeometryReview(host, evidence)
  expect(host.textContent).toContain('Candidate is isolated and not approved')
  expect(host.textContent).toContain('F1: Extrude 1')
  expect(host.textContent).toContain('Heavy-atom contacts < 0.080 nm')
  expect(host.textContent).toContain('1/1 native 2HB cases pass')
  expect(host.textContent).toContain('1 Current builds contain nonfinite atoms')
  host.querySelector('[data-ref="junctions"] button').click()
  expect(viewers[0].focusAtoms).toHaveBeenCalledWith([1, 2, 3])
  const select = host.querySelector('select'); select.value = 'full'; select.dispatchEvent(new Event('change'))
  expect(viewers[0].setRepresentation).toHaveBeenCalledWith('full')
  expect(review.isRendered()).toBe(true)
  review.dispose(); review.dispose()
  expect(host.children).toHaveLength(0)
  for (const view of viewers) expect(view.dispose).toHaveBeenCalledOnce()
})
