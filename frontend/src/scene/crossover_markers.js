/**
 * Crossover markers — gold sphere markers at valid crossover positions.
 *
 * When activated for a helix pair, fetches pre-computed valid positions from
 * the API and renders gold markers in the scene.  Clicking a marker places a
 * crossover between the relevant strands.
 *
 * Usage:
 *   const cm = initCrossoverMarkers(scene, camera, store)
 *   cm.activate(helixAId, helixBId)   // shows markers, enters placement mode
 *   cm.deactivate()                    // removes markers, exits placement mode
 */

import * as THREE from 'three'
import { store } from '../state/store.js'
import * as api from '../api/client.js'

const MARKER_COLOR  = 0xffd700   // gold
const MARKER_RADIUS = 0.12       // nm
const MARKER_GEO    = new THREE.SphereGeometry(MARKER_RADIUS, 8, 6)

export function initCrossoverMarkers(scene, camera, canvas) {
  const _markerGroup = new THREE.Group()
  scene.add(_markerGroup)

  const _raycaster = new THREE.Raycaster()
  const _ndc       = new THREE.Vector2()
  let   _active    = false
  let   _helixAId  = null
  let   _helixBId  = null
  let   _candidates = []   // [{ bp_a, bp_b, distance_nm, midpoint }]
  let   _meshes     = []

  function _clear() {
    _markerGroup.clear()
    _meshes = []
    _candidates = []
  }

  function _posForNuc(geometry, helixId, bpIndex, direction) {
    if (!geometry) return null
    const nuc = geometry.find(
      n => n.helix_id === helixId && n.bp_index === bpIndex && n.direction === direction
    )
    return nuc ? nuc.backbone_position : null
  }

  async function activate(helixAId, helixBId) {
    deactivate()
    _active   = true
    _helixAId = helixAId
    _helixBId = helixBId

    store.setState({ crossoverPlacement: { helixAId, helixBId, markers: [] } })

    const result = await api.getValidCrossoverPositions(helixAId, helixBId)
    if (!result || !result.positions.length) {
      console.warn('No valid crossover positions found for this helix pair.')
      return
    }

    const geometry = store.getState().currentGeometry
    _candidates = result.positions

    for (const pos of result.positions) {
      // Compute midpoint between the two backbone beads for marker placement.
      const posA = _posForNuc(geometry, helixAId, pos.bp_a, 'FORWARD')
        ?? _posForNuc(geometry, helixAId, pos.bp_a, 'REVERSE')
      const posB = _posForNuc(geometry, helixBId, pos.bp_b, 'FORWARD')
        ?? _posForNuc(geometry, helixBId, pos.bp_b, 'REVERSE')

      if (!posA || !posB) continue

      const mid = [
        (posA[0] + posB[0]) / 2,
        (posA[1] + posB[1]) / 2,
        (posA[2] + posB[2]) / 2,
      ]

      const mesh = new THREE.Mesh(MARKER_GEO, new THREE.MeshPhongMaterial({ color: MARKER_COLOR }))
      mesh.position.set(...mid)
      mesh.userData = { bp_a: pos.bp_a, bp_b: pos.bp_b, distance_nm: pos.distance_nm }
      _markerGroup.add(mesh)
      _meshes.push(mesh)
    }
  }

  function deactivate() {
    _active   = false
    _helixAId = null
    _helixBId = null
    _clear()
    store.setState({ crossoverPlacement: null })
  }

  async function _handleClick(e) {
    if (!_active || !_meshes.length) return
    if (e.button !== 0) return

    const rect = canvas.getBoundingClientRect()
    _ndc.set(
      ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    )
    _raycaster.setFromCamera(_ndc, camera)
    const hits = _raycaster.intersectObjects(_meshes)
    if (!hits.length) return

    const { bp_a, bp_b } = hits[0].object.userData
    const geometry = store.getState().currentGeometry
    const design   = store.getState().currentDesign

    // Find the strands that occupy bp_a on helix_a and bp_b on helix_b.
    const nucA = geometry?.find(n => n.helix_id === _helixAId && n.bp_index === bp_a)
    const nucB = geometry?.find(n => n.helix_id === _helixBId && n.bp_index === bp_b)

    if (!nucA?.strand_id || !nucB?.strand_id) {
      console.warn('Could not find strands for crossover placement.')
      return
    }

    // Find domain indices for each strand.
    const strandA = design?.strands?.find(s => s.id === nucA.strand_id)
    const strandB = design?.strands?.find(s => s.id === nucB.strand_id)
    if (!strandA || !strandB) return

    const domIdxA = strandA.domains.findIndex(
      d => d.helix_id === _helixAId && bp_a >= Math.min(d.start_bp, d.end_bp) && bp_a <= Math.max(d.start_bp, d.end_bp)
    )
    const domIdxB = strandB.domains.findIndex(
      d => d.helix_id === _helixBId && bp_b >= Math.min(d.start_bp, d.end_bp) && bp_b <= Math.max(d.start_bp, d.end_bp)
    )

    if (domIdxA < 0 || domIdxB < 0) {
      console.warn('No domain covers the selected bp on one of the helices.')
      return
    }

    const result = await api.addCrossover({
      strandAId:    nucA.strand_id,
      domainAIndex: domIdxA,
      strandBId:    nucB.strand_id,
      domainBIndex: domIdxB,
      crossoverType: nucA.is_scaffold ? 'SCAFFOLD' : 'STAPLE',
    })

    if (result) {
      deactivate()
    } else {
      const err = store.getState().lastError
      console.error('Crossover placement failed:', err?.message)
    }
  }

  // Attach to window (not canvas) so we catch clicks during placement mode.
  window.addEventListener('pointerup', _handleClick)

  // Re-activate if the design changes while markers are shown (geometry rebuilt).
  store.subscribe((newState, prevState) => {
    if (_active && newState.currentGeometry !== prevState.currentGeometry) {
      const aid = _helixAId
      const bid = _helixBId
      deactivate()
      activate(aid, bid)
    }
  })

  return { activate, deactivate, isActive: () => _active }
}
