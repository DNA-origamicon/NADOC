// @vitest-environment jsdom
import { it, expect, vi, afterEach } from 'vitest'
import { initGrapheneDisplayControls } from './graphene_display_controls.js'

afterEach(() => { document.body.innerHTML = ''; localStorage.clear() })
it('changes both renderers and remembers preferences without touching simulation inclusion', () => {
  document.body.innerHTML = '<input id="md-surface-enable" type="checkbox" checked><input id="md-graphene-show" type="checkbox"><select id="md-graphene-representation"><option value="plane">Plane</option><option value="ball">Ball</option><option value="stick">Stick</option></select>'
  const preview = { setDisplay: vi.fn() }, simulation = { setGrapheneDisplay: vi.fn() }
  const inclusion = document.getElementById('md-surface-enable'), onInclude = vi.fn()
  inclusion.addEventListener('change', onInclude)
  const ctrl = initGrapheneDisplayControls({ preview, simulation })
  const show = document.getElementById('md-graphene-show'), rep = document.getElementById('md-graphene-representation')
  show.click(); rep.value = 'stick'; rep.dispatchEvent(new Event('change'))
  expect(preview.setDisplay).toHaveBeenLastCalledWith({ visible: false, representation: 'stick' })
  expect(simulation.setGrapheneDisplay).toHaveBeenLastCalledWith({ visible: false, representation: 'stick' })
  expect(inclusion.checked).toBe(true); expect(onInclude).not.toHaveBeenCalled()
  ctrl.dispose()
  const restored = initGrapheneDisplayControls({ preview, simulation })
  expect(show.checked).toBe(false); expect(rep.value).toBe('stick')
  restored.dispose()
})
