// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { initDebugMenu } from './debug_menu.js'

class Vector2 { set() {} }
class Raycaster {
  setFromCamera() {}
  intersectObject() { return [] }
}

function fixture() {
  document.body.innerHTML = [
    'menu-debug-lod-hud',
    'menu-debug-hull-cluster',
    'menu-debug-wireframe',
    'menu-debug-doubleside',
    'menu-debug-opaque',
    'menu-debug-copy-camera',
    'menu-debug-inspect',
    'menu-debug-mrdna-roundtrip',
  ].map(id => `<button id="${id}"></button>`).join('') + '<canvas></canvas>'
  const material = {
    userData: {}, wireframe: false, side: 0, transparent: true, needsUpdate: false,
  }
  const deps = {
    THREE: { DoubleSide: 2, Raycaster, Vector2 },
    camera: { position: { x: 1, y: 2, z: 3 } },
    canvas: document.querySelector('canvas'),
    controls: { target: { x: 4, y: 5, z: 6 } },
    designRenderer: { getHelixCtrl: () => ({ root: { traverse: fn => fn({ material }) } }) },
    docHeaders: () => ({}),
    getJointRenderer: () => null,
    setMenuToggle: vi.fn(),
    showToast: vi.fn(),
    store: { getState: () => ({ currentDesign: null }) },
  }
  return { deps, material }
}

describe('initDebugMenu', () => {
  beforeEach(() => {
    delete window.__NADOC_DBG__
    delete window.__NADOC_LOD_HUD__
  })

  it('toggles render diagnostics and restores original material values', () => {
    const { deps, material } = fixture()
    initDebugMenu(deps)
    const button = document.getElementById('menu-debug-wireframe')
    button.click()
    expect(material.wireframe).toBe(true)
    expect(material.needsUpdate).toBe(true)
    expect(deps.setMenuToggle).toHaveBeenLastCalledWith('menu-debug-wireframe', true)
    button.click()
    expect(material.wireframe).toBe(false)
  })

  it('explains unavailable LOD diagnostics', () => {
    const { deps } = fixture()
    initDebugMenu(deps)
    document.getElementById('menu-debug-lod-hud').click()
    expect(deps.showToast).toHaveBeenCalledWith(
      expect.stringContaining('Shared renderer not active'),
      { severity: 'warn' },
    )
  })

  it('does not launch a round trip without an active design', () => {
    const { deps } = fixture()
    initDebugMenu(deps)
    document.getElementById('menu-debug-mrdna-roundtrip').click()
    expect(deps.showToast).toHaveBeenCalledWith('No design loaded.', { severity: 'error' })
  })
})
