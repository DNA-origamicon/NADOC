import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { initGeometryReview } from './geometry_review.js'

let review
beforeEach(() => {
  document.body.innerHTML = '<button id="menu-help-geometry-review">geometry Review</button>'
  // jsdom has no dialog top layer; the actual modal/focus behavior is covered in app.
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false }
})
afterEach(() => { review?.dispose(); vi.restoreAllMocks() })

function setup(cases) {
  const contents = []
  const mountGeometryReview = vi.fn((host, bundle) => {
    host.textContent = bundle.label
    const content = { dispose: vi.fn(), isRendered: () => true }
    contents.push(content)
    return content
  })
  review = initGeometryReview({ cases, loadRenderer: async () => ({ mountGeometryReview }) })
  return { contents, mountGeometryReview }
}

it('opens from Help, shares a bundle across cases, disposes views and reloads after close', async () => {
  const load = vi.fn(async () => ({ label: 'Platform', controls: { clear: { label: 'Clean control' } } }))
  const { contents } = setup([{ id: 'platform', title: 'Platform', load },
    { id: 'clear', title: 'Clean', load, control: 'clear' }])
  document.querySelector('button').click()
  await vi.waitFor(() => expect(review.element.dataset.ready).toBe('true'))
  const select = review.element.querySelector('select')
  select.value = 'clear'; select.dispatchEvent(new Event('change'))
  await vi.waitFor(() => expect(review.element.dataset.case).toBe('clear'))
  expect(load).toHaveBeenCalledTimes(1)
  expect(contents[0].dispose).toHaveBeenCalledOnce()
  expect(review.element.textContent).toContain('Clean control')
  review.element.querySelector('.gr-close').click()
  expect(contents[1].dispose).toHaveBeenCalledOnce()
  expect(review.element.querySelector('.gr-body').children).toHaveLength(0)
  expect(load.mock.calls[0][0].signal.aborted).toBe(true)
  review.show()
  await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(2))
})

it('drops a late response after close and never mounts it into the next opening', async () => {
  let resolve
  const load = vi.fn().mockImplementationOnce(() => new Promise(r => { resolve = r }))
    .mockResolvedValue({ label: 'Fresh' })
  const { mountGeometryReview } = setup([{ id: 'one', title: 'One', load }])
  review.show(); review.close(); review.show()
  await vi.waitFor(() => expect(mountGeometryReview).toHaveBeenCalledOnce())
  resolve({ label: 'Stale' })
  await Promise.resolve(); await Promise.resolve()
  expect(mountGeometryReview).toHaveBeenCalledOnce()
  expect(review.element.textContent).toContain('Fresh')
})

it('shows load failures and retries without retaining a rejected promise', async () => {
  const load = vi.fn().mockRejectedValueOnce(new Error('Missing evidence')).mockResolvedValue({ label: 'Ready' })
  setup([{ id: 'one', title: 'One', load }])
  review.show()
  await vi.waitFor(() => expect(review.element.querySelector('[role="alert"]')?.textContent).toBe('Missing evidence'))
  review.element.querySelector('.gr-body button').click()
  await vi.waitFor(() => expect(review.element.dataset.ready).toBe('true'))
  expect(load).toHaveBeenCalledTimes(2)
})

it('loads the selected case renderer without loading the unrelated default renderer', async () => {
  const loadRenderer = vi.fn()
  const dispose = vi.fn()
  const custom = vi.fn(async () => ({ mountGeometryReview(host, bundle) {
    host.textContent = bundle.label
    return { dispose, isRendered: () => true }
  } }))
  review = initGeometryReview({ loadRenderer, cases: [{ id: 'direct', title: 'Direct',
    load: async () => ({ label: 'Preserved linker' }), loadRenderer: custom }] })
  review.show()
  await vi.waitFor(() => expect(review.element.dataset.ready).toBe('true'))
  expect(review.element.textContent).toContain('Preserved linker')
  expect(custom).toHaveBeenCalledOnce()
  expect(loadRenderer).not.toHaveBeenCalled()
  review.close()
  expect(dispose).toHaveBeenCalledOnce()
})

it('Escape releases content, shortcuts do not bubble to the editor, and disposal removes the menu handler', async () => {
  const { contents } = setup([{ id: 'one', title: 'One', load: async () => ({ label: 'Ready' }) }])
  review.show()
  await vi.waitFor(() => expect(review.element.dataset.ready).toBe('true'))
  const shortcut = vi.fn()
  window.addEventListener('keydown', shortcut)
  try {
    review.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true }))
    expect(shortcut).not.toHaveBeenCalled()
    review.element.dispatchEvent(new Event('cancel', { cancelable: true }))
    expect(review.element.open).toBe(false)
    expect(contents[0].dispose).toHaveBeenCalledOnce()
    review.dispose()
    document.querySelector('button').click()
    expect(document.querySelector('dialog')).toBeNull()
  } finally { window.removeEventListener('keydown', shortcut) }
})
