import { expect, it, vi } from 'vitest'
import { createAnnotationController } from './annotation_controller.js'
import { createAnnotationPresentationController } from './annotation_presentation_controller.js'
import { PRESENTATION_EVENT } from './presentation_checkpoint_animation.js'

it('renders saved notes without editing/autosaving the live controller, then restores it', () => {
  const commit = vi.fn()
  const controller = createAnnotationController({ commit, legacyStorage: null })
  controller.syncFromDesign({ id: 'part', annotations: [{ id: 'a', text: 'Working' }] })
  const display = createAnnotationPresentationController({ controller, getDocument: () => ({ id: 'part' }) })
  const changed = vi.fn(), off = display.subscribe(changed)
  window.dispatchEvent(new CustomEvent(PRESENTATION_EVENT, { detail: {
    documentId: 'part', state: { annotations: [{ id: 'a', text: 'Checkpoint' }], annotations_enabled: true },
  } }))
  expect(display.list()[0].text).toBe('Checkpoint')
  display.update('a', { text: 'Drag during playback' })
  expect(controller.list()[0].text).toBe('Working')
  expect(controller.hasPendingEdits()).toBe(false)
  expect(commit).not.toHaveBeenCalled()
  window.dispatchEvent(new CustomEvent(PRESENTATION_EVENT, { detail: null }))
  expect(display.list()[0].text).toBe('Working')
  expect(changed).toHaveBeenCalledTimes(2)
  off(); display.dispose(); controller.dispose()
})

it('immediately mirrors working edits into selected notes without exposing excluded annotations', () => {
  const controller = createAnnotationController({ legacyStorage: null })
  controller.syncFromDesign({ id: 'part', annotations: [{ id: 'a', text: 'Old', visible: false }, { id: 'b', text: 'Excluded' }] })
  const display = createAnnotationPresentationController({ controller, getDocument: () => ({ id: 'part' }) })
  window.dispatchEvent(new CustomEvent(PRESENTATION_EVENT, { detail: {
    documentId: 'part', annotationIds: ['a'], state: { annotations: [{ id: 'a', text: 'Old' }], annotations_enabled: true },
  } }))
  controller.update('a', { text: 'New', fontFamily: 'Georgia', size: 2 })
  expect(display.list()).toHaveLength(1)
  expect(display.get('a')).toMatchObject({ text: 'New', fontFamily: 'Georgia', size: 2, visible: true })
  expect(controller.get('a').visible).toBe(false)
  window.dispatchEvent(new CustomEvent(PRESENTATION_EVENT, { detail: {
    documentId: 'part', annotationIds: ['a'], state: { annotations: [{ id: 'a', text: 'Old' }], annotations_enabled: true },
  } }))
  expect(display.get('a')).toMatchObject({ text: 'New', fontFamily: 'Georgia', size: 2 })
  controller.update('b', { text: 'Still excluded' })
  expect(display.list()).toHaveLength(1)
  controller.remove('a')
  expect(display.list()).toEqual([])
  window.dispatchEvent(new CustomEvent(PRESENTATION_EVENT, { detail: {
    documentId: 'part', liveAnnotations: true, state: { annotations: [{ id: 'b', text: 'Stale' }], annotations_enabled: true },
  } }))
  expect(display.get('b').text).toBe('Still excluded')
  display.dispose(); controller.dispose()
})
