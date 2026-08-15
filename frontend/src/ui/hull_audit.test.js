// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { buildClusteredAuditHull, disposeTree, hullAuditStats, initHullAudit, partitionAuditGeometry, setHullElementBoundaries } from './hull_audit.js'

beforeEach(() => {
  document.body.innerHTML = '<button id="menu-help-hull-audit"></button>'
})

describe('Hull Audit', () => {
  it('reports geometry size and triangle count', () => {
    const root = new THREE.Group()
    root.add(new THREE.Mesh(new THREE.BoxGeometry(2, 4, 6), new THREE.MeshBasicMaterial()))
    expect(hullAuditStats(root)).toMatchObject({ meshes: 1, triangles: 12, size: [2, 4, 6] })
  })

  it('toggles only the candidate elemental boundary layer', () => {
    const root = new THREE.Group()
    const unified = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
    unified.userData.hullUnifiedSurface = true
    const boundary = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial())
    boundary.userData.hullElementBoundaries = true
    boundary.visible = false
    const colors = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
    colors.userData.hullElementColors = true
    colors.visible = false
    root.add(unified, boundary, colors)
    expect(setHullElementBoundaries(root, true)).toBe(2)
    expect(boundary.visible).toBe(true)
    expect(colors.visible).toBe(true)
    expect(unified.visible).toBe(false)
    expect(setHullElementBoundaries(root, false)).toBe(2)
    expect(boundary.visible).toBe(false)
    expect(colors.visible).toBe(false)
    expect(unified.visible).toBe(true)
  })

  it('does not dispose shared Full-reference geometry', () => {
    const root = new THREE.Group(), geometry = new THREE.BoxGeometry()
    geometry.userData.shared = true
    const dispose = vi.spyOn(geometry, 'dispose')
    root.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial()))
    disposeTree(root)
    expect(dispose).not.toHaveBeenCalled()
  })

  it('toggles a read-only audit shell and explains missing geometry', () => {
    const setMenuToggle = vi.fn()
    const audit = initHullAudit({ getState: () => ({}), setMenuToggle, viewerFactory: vi.fn() })
    document.getElementById('menu-help-hull-audit').click()
    expect(audit.isOpen()).toBe(true)
    expect(audit.element.classList.contains('visible')).toBe(true)
    expect(audit.element.textContent).toContain('Load a design')
    expect(setMenuToggle).toHaveBeenLastCalledWith('menu-help-hull-audit', true)
    document.getElementById('menu-help-hull-audit').click()
    expect(audit.isOpen()).toBe(false)
    expect(setMenuToggle).toHaveBeenLastCalledWith('menu-help-hull-audit', false)
    audit.dispose()
  })

  it('refreshes an open audit when cluster transforms change', async () => {
    let listener
    const unsubscribe = vi.fn()
    const getState = vi.fn(() => ({}))
    const audit = initHullAudit({
      getState,
      subscribe: callback => { listener = callback; return unsubscribe },
      viewerFactory: vi.fn(),
    })
    audit.show()
    const callsAfterOpen = getState.mock.calls.length
    const previous = { currentDesign: { cluster_transforms: [] } }
    const next = { currentDesign: { cluster_transforms: [{ id: 'moved' }] } }
    listener(next, previous)
    await Promise.resolve()
    expect(getState.mock.calls.length).toBe(callsAfterOpen + 1)
    audit.dispose()
    expect(unsubscribe).toHaveBeenCalledOnce()
  })

  it('splits finer clusters without reapplying their committed world transform', () => {
    const helices = [
      { id: 'a', grid_pos: [0, 0], loop_skips: [] },
      { id: 'b', grid_pos: [0, 2], loop_skips: [] },
      { id: 'c', grid_pos: [0, 4], loop_skips: [] },
    ]
    const geometry = helices.flatMap((h, i) => [0, 1].flatMap(bp => ['s', 't'].map(strand => ({
      helix_id: h.id, bp_index: bp, strand_id: `${strand}${i}`,
      backbone_position: [i * 4.5, i === 1 ? 12 : 0, bp],
    }))))
    const axes = Object.fromEntries(helices.map((h, i) => [h.id, {
      start: [i * 4.5, i === 1 ? 12 : 0, 0], end: [i * 4.5, i === 1 ? 12 : 0, 1],
    }]))
    const design = {
      lattice_type: 'SQUARE', helices, strands: [], metadata: {},
      cluster_transforms: [
        { id: 'left', helix_ids: ['a'], translation: [0, 0, 0], rotation: [0, 0, 0, 1], pivot: [0, 0, 0] },
        { id: 'moved', helix_ids: ['b'], translation: [0, 12, 0], rotation: [0, 0, 0, 1], pivot: [0, 0, 0] },
      ],
    }
    const root = buildClusteredAuditHull(design, geometry, axes)
    const moved = root.children.find(child => child.userData.hullAuditClusterId === 'moved')
    expect(root.children).toHaveLength(3)
    const box = new THREE.Box3().setFromObject(moved)
    expect(box.getCenter(new THREE.Vector3()).y).toBeCloseTo(12)
    root.traverse(obj => { obj.geometry?.dispose(); obj.material?.dispose() })
  })

  it('partitions partial-domain clusters without claiming the rest of a helix', () => {
    const design = {
      helices: [{ id: 'a' }, { id: 'b' }],
      strands: [
        { id: 's', domains: [{ helix_id: 'a', start_bp: 0, end_bp: 2 }, { helix_id: 'a', start_bp: 2, end_bp: 4 }] },
        { id: 't', domains: [{ helix_id: 'a', start_bp: 0, end_bp: 2 }, { helix_id: 'a', start_bp: 2, end_bp: 4 }] },
      ],
      cluster_transforms: [{
        id: 'partial', helix_ids: ['a'],
        domain_ids: [{ strand_id: 's', domain_index: 0 }, { strand_id: 't', domain_index: 0 }],
      }],
    }
    const geometry = [
      { helix_id: 'a', bp_index: 0, strand_id: 's' },
      { helix_id: 'a', bp_index: 0, strand_id: 't', domain_index: 0 },
      { helix_id: 'a', bp_index: 3, strand_id: 's', domain_index: 1 },
      { helix_id: 'a', bp_index: 3, strand_id: 't', domain_index: 1 },
      { helix_id: 'b', bp_index: 0, strand_id: 'u', domain_index: 0 },
    ]
    const partition = partitionAuditGeometry(design, geometry)
    expect(partition.buckets.get('partial')).toEqual(geometry.slice(0, 2))
    expect(partition.unclustered).toEqual(geometry.slice(2))
  })
})
