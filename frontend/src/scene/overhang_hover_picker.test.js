import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { nearestAnchorToPoint, initOverhangHoverPicker } from './overhang_hover_picker.js'

// Camera looking down -z at the origin; world (0,0,0) projects to screen centre.
function camera() {
  const cam = new THREE.PerspectiveCamera(50, 1, 0.1, 100)
  cam.position.set(0, 0, 10)
  cam.lookAt(0, 0, 0)
  cam.updateMatrixWorld()
  cam.updateProjectionMatrix()
  return cam
}
const rect = { left: 0, top: 0, width: 200, height: 200 }
const anchor = (id, world, overhangId = 'o', label = 'L') => ({ instanceId: id, overhangId, label, world: new THREE.Vector3(...world) })

describe('nearestAnchorToPoint', () => {
  it('returns the anchor whose projection is closest (within radius)', () => {
    const best = nearestAnchorToPoint([anchor(1, [0, 0, 0])], camera(), rect, 100, 100, 40)
    expect(best?.instanceId).toBe(1) // origin → screen centre (100,100)
  })
  it('returns null when the nearest is beyond the radius', () => {
    expect(nearestAnchorToPoint([anchor(1, [0, 0, 0])], camera(), rect, 0, 0, 5)).toBeNull()
  })
  it('returns null for empty / oversized anchor sets', () => {
    expect(nearestAnchorToPoint([], camera(), rect, 100, 100, 40)).toBeNull()
    expect(nearestAnchorToPoint(new Array(1201).fill(anchor(1, [0, 0, 0])), camera(), rect, 100, 100, 40)).toBeNull()
  })
})

describe('initOverhangHoverPicker', () => {
  function setup({ toolActive = true } = {}) {
    const setHovered = vi.fn()
    const anchors = [anchor(7, [0, 0, 0], 'oX', 'lbl')]
    const picker = initOverhangHoverPicker({
      camera: camera(),
      canvas: { getBoundingClientRect: () => rect },
      getAnchors: () => anchors,
      setHovered,
      getToolActive: () => toolActive,
    })
    return { picker, setHovered }
  }

  it('nearestAt maps the hit anchor to {instanceId, overhangId, label}', () => {
    expect(setup().picker.nearestAt(100, 100)).toEqual({ instanceId: 7, overhangId: 'oX', label: 'lbl' })
  })

  it('onHoverMove notifies the renderer with the hovered overhang (deduped)', () => {
    const { picker, setHovered } = setup()
    picker.onHoverMove({ buttons: 0, clientX: 100, clientY: 100 })
    expect(setHovered).toHaveBeenCalledWith(expect.objectContaining({ instanceId: 7 }))
    setHovered.mockClear()
    picker.onHoverMove({ buttons: 0, clientX: 100, clientY: 100 }) // same key → no re-notify
    expect(setHovered).not.toHaveBeenCalled()
  })

  it('skips while a mouse button is held', () => {
    const { picker, setHovered } = setup()
    picker.onHoverMove({ buttons: 1, clientX: 100, clientY: 100 })
    expect(setHovered).not.toHaveBeenCalled()
  })

  it('reset() clears the hovered overhang', () => {
    const { picker, setHovered } = setup()
    picker.reset()
    expect(setHovered).toHaveBeenCalledWith(null)
  })
})
