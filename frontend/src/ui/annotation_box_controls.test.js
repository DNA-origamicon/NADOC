import { expect, it } from 'vitest'
import { createAnnotationController } from '../scene/annotation_controller.js'
import { createAnnotationBoxControls } from './annotation_box_controls.js'
it('edits dimensions and angle, mirrors viewport edits, and resets to automatic sizing', () => {
  const controller = createAnnotationController({ legacyStorage: null })
  controller.syncFromDesign({ id: 'a', annotations: [] })
  const entry = controller.add({ text: 'Caption', size: 2 })
  const controls = createAnnotationBoxControls({ document, controller, id: entry.id })
  const edit = (name, value) => {
    const input = controls.root.querySelector(`[data-field="box-${name}"]`)
    input.value = value; input.dispatchEvent(new Event('change'))
  }
  edit('width', '400'); edit('height', '150'); edit('angle', '450')
  expect(controller.get(entry.id)).toMatchObject({ boxSize: { w: 400, h: 150 }, rotationDeg: 90, size: 2 })
  controller.update(entry.id, { boxSize: { w: 500, h: 200 } })
  expect(controls.root.querySelector('[data-field="box-width"]').value).toBe('500')
  controls.root.querySelector('button').click()
  expect(controller.get(entry.id)).toMatchObject({ boxSize: null, rotationDeg: 90 })
  controls.dispose(); controller.dispose()
})
