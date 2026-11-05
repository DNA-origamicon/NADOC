import { it, expect } from 'vitest'
import { selectedSequenceKeys, highlightOverhangCell } from './sequence_selection.js'
import { strandSequenceDisplay, renderStrandSequence } from './strand_sequence_display.js'
import { junctionFixture } from '../test-helpers/strand_junction_fixture.js'
import { sequenceSelectionRefs } from '../cadnano-editor/sequence_selection.js'
import { domainLineKey, domainEndKey, xoverKey } from '../cadnano-editor/element_keys.js'

it('highlights only the selected reverse domain, respecting loops and skips', () => {
  const { strand, design } = junctionFixture()
  design.helices[1].loop_skips = [{ bp_index: 2, delta: 1 }, { bp_index: 1, delta: -1 }]
  const result = selectedSequenceKeys(design, [{ kind: 'domain', strandId: strand.id, domainIndex: 1 }])
  expect([...result.get(strand.id)]).toEqual(['b:2:REVERSE', 'b:2:REVERSE:1', 'b:0:REVERSE'])
})
it.each([false, true])('selects junction endpoints and inserted bases, forced=%s', forced => {
  const { strand, design } = junctionFixture(forced)
  const selected = selectedSequenceKeys(design, [{ kind: 'crossover', id: forced ? 'fl:1' : 'xo', subtype: forced ? 'forced_ligation' : 'crossover' }]).get(strand.id)
  const span = document.createElement('span')
  renderStrandSequence(span, strandSequenceDisplay(strand, design), selected)
  expect([...span.querySelectorAll('mark')].map(m => m.textContent).join('')).toBe('GATTTTTG')
  expect(span.textContent).toBe('ACGATTTTTGCA')
  expect(selectedSequenceKeys(design, []).size).toBe(0)
})
it('shows the precise overhang section while retaining the editable input', () => {
  const { strand, design } = junctionFixture()
  const domain = strand.domains[0]
  domain.overhang_id = 'oh'
  const selected = selectedSequenceKeys(design, [{ kind: 'overhang', id: 'oh' }]).get(strand.id)
  const cell = document.createElement('td')
  cell.innerHTML = '<input value="ACG">'
  highlightOverhangCell(cell, domain, design, selected)
  expect(cell.querySelector('input').value).toBe('ACG')
  expect([...cell.querySelectorAll('mark')].map(m => m.textContent).join('')).toBe('ACG')
  cell.querySelector('input').value = 'TTT'
  cell.querySelector('input').dispatchEvent(new Event('input'))
  expect([...cell.querySelectorAll('mark')].map(m => m.textContent).join('')).toBe('TTT')
})
it('translates cadnano domain, end and crossover elements to exact sequence refs', () => {
  const { strand, design } = junctionFixture()
  const refs = sequenceSelectionRefs(design, new Set([domainLineKey(strand.domains[1]), domainEndKey(strand.domains[0], '5p'), xoverKey(design.crossovers[0])]))
  expect(refs).toContainEqual({ kind: 'domain', strandId: 's', domainIndex: 1 })
  expect(refs).toContainEqual({ kind: 'base', key: 'a:0:FORWARD' })
  expect(refs).toContainEqual({ kind: 'crossover', id: 'xo' })
  expect(selectedSequenceKeys(design, refs).get('s').has('a:1:FORWARD')).toBe(false)
})
it('keeps a single base precise and renders unassigned selected domains as Ns', () => {
  const { strand, design } = junctionFixture()
  strand.sequence = null
  design.crossovers = []
  const selected = selectedSequenceKeys(design, [{ kind: 'base', key: 'b:1:REVERSE' }]).get('s')
  const span = document.createElement('span')
  renderStrandSequence(span, strandSequenceDisplay(strand, design, selected), selected)
  expect(span.textContent).toBe('NNNNNN')
  expect(span.querySelectorAll('mark')).toHaveLength(1)
})
it('unions disjoint selections without selecting the rest of the strand', () => {
  const { design } = junctionFixture()
  const selected = selectedSequenceKeys(design, [
    { kind: 'domain', strandId: 's', domainIndex: 1 },
    { kind: 'base', key: 'a:0:FORWARD' },
    { kind: 'base', key: '__xb__:xo:3' },
  ]).get('s')
  expect([...selected].sort()).toEqual(['__xb__:xo:3', 'a:0:FORWARD', 'b:0:REVERSE', 'b:1:REVERSE', 'b:2:REVERSE'])
})
