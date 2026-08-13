import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.resolve(HERE, '..')
const read = relative => readFileSync(path.resolve(HERE, relative), 'utf8')
const manager = read('./selection_manager.js')
const controller = read('./selection_controller.js')
const selectionRefs = read('./selection_ref.js')
const store = read('../state/store.js')
const main = read('../main.js')

function productionJavaScript(dir = SRC) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const absolute = path.join(dir, entry.name)
    if (entry.isDirectory()) return productionJavaScript(absolute)
    if (!entry.name.endsWith('.js') || /\.(?:test|spec)\.js$/.test(entry.name)) return []
    return [{ absolute, relative: path.relative(SRC, absolute), source: readFileSync(absolute, 'utf8') }]
  })
}

describe('selection architecture — canonical enforcement', () => {
  it('has deleted every legacy design-selection field from production', () => {
    const forbidden = [
      'selectedObject', 'multiSelectedStrandIds', 'multiSelectedDomainIds',
      'multiSelectedOverhangIds', 'multiSelectedExtensionIds',
      'multiSelectedClusterIds', 'multiSelectedBaseKeys',
      'projectLegacySelection', 'legacySelectionDrift', 'assertSynchronized',
    ]
    const violations = productionJavaScript().flatMap(file => forbidden
      .filter(token => file.source.includes(token))
      .map(token => `${file.relative}: ${token}`))
    expect(violations).toEqual([])
  })

  it('keeps the controller as the sole canonical selection writer', () => {
    const writers = productionJavaScript()
      .filter(file => /store\.setState\(\{\s*selection\s*:/.test(file.source))
      .map(file => file.relative)
    expect(writers).toEqual(['scene/selection_controller.js'])
    expect(controller).toContain('store.setState({ selection: canonical })')
    expect(store).not.toMatch(/\bselection\s*:\s*createSelectionState\([^)]*\),\s*\n\s*(?:selected|multiSelected)/)
  })

  it('requires the controller and has no compatibility routing branches', () => {
    expect(manager).toContain("if (!selectionController) throw new TypeError('selection manager requires the canonical selection controller')")
    expect(manager).not.toContain('if (selectionController)')
    expect(manager).not.toContain('selectionController?.')
    expect(manager).not.toContain('_promoteSelectionToMulti')
  })

  it('keeps programmatic nucleotide selection on the canonical Base endpoint', () => {
    const publicNucleotide = manager.slice(manager.indexOf('selectNucleotide(nuc)'), manager.indexOf('selectOverhang(overhangId)'))
    expect(publicNucleotide).toContain('_setBaseKeys([key])')
    expect(publicNucleotide).not.toContain("type: 'nucleotide'")

    const baseCommit = manager.slice(manager.indexOf('function _setBaseKeys'), manager.indexOf('function _selectBaseKey'))
    expect(baseCommit).toContain('selectionController.replace')
  })

  it('routes gestures through intents and paints only in the canonical projector', () => {
    const endSelect = manager.slice(manager.indexOf('function _selectEndV2'), manager.indexOf('function _selectConeV2'))
    expect(endSelect).toContain('selectionController.select(ref)')
    expect(endSelect).not.toContain('_applyEndSelection')

    const coneSelect = manager.slice(manager.indexOf('function _selectConeV2'), manager.indexOf('function _v2HandleBead'))
    expect(coneSelect).toContain('selectionController.select(ref)')
    expect(coneSelect).not.toContain('_highlightCone')

    const crossoverToggle = manager.slice(manager.indexOf('function _toggleCrossover'), manager.indexOf('function _toggleEndBead'))
    expect(crossoverToggle).toContain('selectionController.toggle(ref)')

    const projector = manager.slice(manager.indexOf('function _syncCanonicalHighlights'), manager.indexOf('function _handleCtrlClickNuc'))
    expect(projector).toContain('selectionHighlightDescriptor(state)')
    expect(projector).toContain('_coneForBond')
    expect(projector).toContain('_clearMultiSelection({ commit: false })')
    expect(projector).toContain('_applyMultiCrossoverHighlight')
    expect(projector).toContain('_applyEndSelection')
    expect(projector).toContain('_repaintBaseGlow')
  })

  it('keeps measurement anchors transient and separate from canonical End refs', () => {
    expect(manager).toMatch(/let _ctrlBeads\s*=\s*\[\]/)
    expect(manager).toContain('getCtrlBeads()')
    expect(manager).toContain('selectedEndRefs(store.getState())')
  })

  it('enforces the explicit design/assembly selection boundary', () => {
    expect(main).toContain("selectionController.reload('assembly')")
    expect(main).toContain("selectionController.reload('design')")
    expect(controller).toContain('current.context !== context')
    expect(selectionRefs).not.toMatch(/'instance'|'partGroup'|'assemblyOverhang'/)
    for (const field of [
      'activeInstanceId', 'multiSelectedInstanceIds', 'activeGroupId',
      'groupDiveStack', 'assemblyOverhangSelection',
    ]) expect(store).toContain(field)
  })
})
