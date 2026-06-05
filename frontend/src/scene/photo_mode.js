// Photo mode + export-representation subsystem (extracted from main.js, #70).
//
// Two coupled concerns:
//   1. Photo mode — the publication-render pane (PBR/HDRI/path-tracer) driven by
//      `photoRenderer` + `initPhotoPanel`. Enter/exit toggle annotation overlays
//      and partial UI lockdown for clean figures.
//   2. Export representation — for the duration of a photo-mode PNG/video render,
//      every instance is temporarily upgraded to the assembly's
//      `export_representation` at full geometric detail, then restored. The
//      `getExportRepActive()` flag lets the save path skip the temporary upgrade
//      so it never hits disk.
//
// Display-layer only — never mutates Design topology.

import * as THREE from 'three'
import { BEAD_RADIUS } from './helix_renderer.js'
import { SPHERE_GEO as ATOM_SPHERE_GEO, CYLINDER_GEO as BOND_CYL_GEO } from './atomistic_renderer/geometry_builder.js'
import { exportPhotoVideo } from './export_video.js'
import { registerShortcut } from '../input/shortcuts.js'
import { initPhotoPanel } from '../ui/photo_panel.js'

/**
 * Pure: from the current store state, decide whether the export render needs to
 * temporarily upgrade every instance's representation, and produce the patch +
 * restore lists. No upgrade when not in assembly mode, no instances, the export
 * rep is 'working', or every instance already matches.
 * @returns {{inAssembly:boolean, exportRep:string, needUpgrade:boolean,
 *            snapshot:Array<{id:string,representation:string}>,
 *            patches:Array<{id:string,representation:string}>}}
 */
export function planExportRepUpgrade(state) {
  const asm = state.currentAssembly
  const exportRep = asm?.export_representation ?? 'full'
  const insts = asm?.instances ?? []
  const inAssembly = !!state.assemblyActive && insts.length > 0
  const needUpgrade = inAssembly && exportRep !== 'working'
    && !insts.every(i => i.representation === exportRep)
  return {
    inAssembly,
    exportRep,
    needUpgrade,
    snapshot: insts.map(i => ({ id: i.id, representation: i.representation })),
    patches:  insts.map(i => ({ id: i.id, representation: exportRep })),
  }
}

export function initPhotoMode({
  store, api, sceneCtx, photoRenderer, assemblyRenderer, designRenderer,
  bluntEnds, assemblyJointRenderer, viewCube, player,
}) {
  const { scene, renderer } = sceneCtx

  let _photoPanelCtrl = null

  // The assembly's `export_representation` is applied to ALL instances only for
  // the duration of a photo-mode PNG/video render, then the working reps are
  // restored. Lets the user edit/preview at a fast LOD but export at high
  // detail. `_exportRepActive` guards saves so the temporary upgrade never hits
  // disk (restore in `finally` + the load-time auto-downgrade are the net).
  let _exportRepActive = false

  /** Batch-patch all instances and resolve when the renderer finishes the
   *  rebuild the store subscriber kicks off. `onRebuildComplete` only appends
   *  (no off-API), so guard a one-shot; a timeout surfaces a stuck rebuild. */
  function _applyRepAndAwaitRebuild(patches) {
    return new Promise((resolve, reject) => {
      let done = false
      const timer = setTimeout(() => {
        if (!done) { done = true; reject(new Error('export rebuild timed out')) }
      }, 120_000)
      assemblyRenderer.onRebuildComplete(() => {
        if (done) return
        done = true; clearTimeout(timer); resolve()
      })
      api.batchPatchInstances(patches).catch(err => {
        if (!done) { done = true; clearTimeout(timer); reject(err) }
      })
    })
  }

  /** Run `fn` (the actual export render) with every instance temporarily set to
   *  the assembly's export representation, restoring the originals afterward.
   *  ALSO suppresses the distance LOD demotion for the whole export so every
   *  part renders at its rep's detail bucket (no far-away hull) → uniform
   *  high-detail figures regardless of zoom.  The rep upgrade is a no-op when
   *  not in assembly mode, no instances, 'working', or already matching; the
   *  LOD suppression still applies whenever we're in an assembly. */
  // High-segment geometry built once on first export, reused thereafter.  The
  // interactive scene keeps its fast low-poly meshes; only the export render uses
  // these.  Atoms/bonds are unit-sized (scaled per-instance); beads/fluorophores
  // bake their radius (instances only translate), so the radius must match the
  // low-poly source (GEO_SPHERE = BEAD_RADIUS, GEO_FLUORO_SPHERE = 0.25).
  let _hdGeoCache = null
  function _highDetailGeometries() {
    if (_hdGeoCache) return _hdGeoCache
    const W = 32, H = 24, RADIAL = 24   // sphere width/height segs; cylinder radial segs
    _hdGeoCache = {
      atom:   new THREE.SphereGeometry(1, W, H),
      bond:   new THREE.CylinderGeometry(1, 1, 1, RADIAL, 1),
      bead:   new THREE.SphereGeometry(BEAD_RADIUS, W, H),
      fluoro: new THREE.SphereGeometry(0.25, W, H),
    }
    return _hdGeoCache
  }

  // Export-only: swap the low-poly interactive sphere/cylinder geometry on
  // atom/bond/bead/fluorophore InstancedMeshes for smooth high-segment versions,
  // run the export, then restore.  Atoms/bonds are matched by shared-geometry
  // reference; CG beads/fluorophores by mesh name (and only when they're still
  // real spheres — skip the opt-in impostor quads).  Swapping `mesh.geometry`
  // leaves instanceMatrix/instanceColor untouched, so positions + colors hold.
  async function _withHighDetailGeometry(fn) {
    const hd = _highDetailGeometries()
    const restore = []   // [mesh, originalGeometry]
    scene.traverse(obj => {
      if (!obj.isInstancedMesh) return
      let hi = null
      if      (obj.geometry === ATOM_SPHERE_GEO) hi = hd.atom
      else if (obj.geometry === BOND_CYL_GEO)    hi = hd.bond
      else if (obj.name === 'backboneSpheres'       && obj.geometry?.type === 'SphereGeometry') hi = hd.bead
      else if (obj.name === 'extensionFluorophores' && obj.geometry?.type === 'SphereGeometry') hi = hd.fluoro
      if (hi && obj.geometry !== hi) { restore.push([obj, obj.geometry]); obj.geometry = hi }
    })
    try { await fn() }
    finally { for (const [mesh, geo] of restore) mesh.geometry = geo }
  }

  async function _withExportRepresentation(fn) {
    // Always export at full geometric detail (smooth atoms/beads/bonds), restored
    // after.  Wraps the actual render so both the rep-upgrade and no-upgrade paths
    // get it; harmless when no atom/bead meshes are present.
    const run = () => _withHighDetailGeometry(fn)
    const { inAssembly, needUpgrade, snapshot, patches } = planExportRepUpgrade(store.getState())
    if (inAssembly) assemblyRenderer.setSuppressLodDemotion?.(true)

    if (!needUpgrade) {
      try { await run() }
      finally { if (inAssembly) assemblyRenderer.setSuppressLodDemotion?.(false) }
      return
    }

    _exportRepActive = true
    try {
      await _applyRepAndAwaitRebuild(patches)
      photoRenderer.resyncMaterials()
      await run()
    } finally {
      try {
        await _applyRepAndAwaitRebuild(snapshot)
        photoRenderer.resyncMaterials()
      } catch (err) {
        console.error('[export-rep] restore failed:', err)
      }
      assemblyRenderer.setSuppressLodDemotion?.(false)
      _exportRepActive = false
    }
  }

  function _photoModeEnter() {
    const leftPanel = document.getElementById('left-panel')

    // Show photo pane directly — bypasses both the locked-hidden guard and the
    // setActiveTab collapsed-toggle behaviour (clicking an active tab collapses;
    // entering photo mode should always expand).
    document.querySelectorAll('#left-panel .tab-content').forEach(el => {
      el.hidden = el.id !== 'tab-content-photo'
    })
    if (leftPanel) {
      leftPanel.classList.remove('hidden')
      // Update tab button active states so the Photo button looks selected.
      document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === 'photo')
      })
    }

    if (!_photoPanelCtrl) {
      _photoPanelCtrl = initPhotoPanel(photoRenderer, sceneCtx, {
        onEnter: _photoModeEnter,
        onExit:  _photoModeExit,
        store,
        player,
        exportPhotoVideo,
        withExportRepresentation: _withExportRepresentation,
        setExportRepresentation: (rep) => api.setAssemblyExportRepresentation(rep),
      })
    }
    photoRenderer.activate({})
    // Apply the persisted active profile (if any) AFTER activate so material
    // setters take effect immediately rather than queueing.
    _photoPanelCtrl?.applyActiveProfile?.()
    _photoPanelCtrl?.syncToState()

    // Suppress annotation overlays that don't belong in publication renders.
    // Design-mode renderer (no-op in assembly mode):
    designRenderer.setAxisArrowsVisible(false)
    bluntEnds?.setVisible(false)
    // Assembly-mode counterparts: per-instance helix axis arrows + helix-id
    // labels + overhang-name sprites + active-instance BoxHelper, plus the
    // orange joint indicators and (mate-mode-only) blunt-end disks drawn by
    // assemblyJointRenderer. setPhotoMode also flags the renderer so any
    // rebuild WHILE photo mode is active (e.g. polymerize mid-photo) keeps
    // the new instances clean too.
    assemblyRenderer.setPhotoMode(true)
    assemblyJointRenderer.setVisible(false)
    // Partial UI lockdown for clean publication renders:
    // hide the view cube + nav HUD; leave selection/orbit/zoom enabled so the
    // user can still frame parts. Active gizmos remain visible (they self-hide
    // when their owning panel exits transform mode).
    viewCube.hide()
    const modeIndicator = document.getElementById('mode-indicator')
    if (modeIndicator) modeIndicator.style.display = 'none'
    store.setState({ photoActive: true })
  }

  function _photoModeExit() {
    // Idempotent: safe to call from any teardown path (file close/open/new,
    // assembly enter) even when photo mode isn't active — just no-op.
    if (!photoRenderer.isActive()) return
    photoRenderer.deactivate()

    // Restore annotation overlays to their pre-photo-mode state.
    designRenderer.setAxisArrowsVisible(true)
    const tf = store.getState().toolFilters
    bluntEnds?.setVisible(tf?.bluntEnds ?? true)
    assemblyRenderer.setPhotoMode(false)
    assemblyJointRenderer.setVisible(true)
    // Restore the partial-lockdown UI.
    viewCube.show()
    const modeIndicator = document.getElementById('mode-indicator')
    if (modeIndicator) modeIndicator.style.display = ''
    store.setState({ photoActive: false })

    const leftPanel = document.getElementById('left-panel')
    if (leftPanel?.classList.contains('locked-hidden')) {
      // No design loaded — hide photo pane and the panel itself.
      document.getElementById('tab-content-photo').hidden = true
      leftPanel.classList.add('hidden')
    } else {
      // Design loaded — restore normal tab state via the sidebar controller.
      window.__leftSidebar?.setActiveTab('feature-log')
    }
  }

  document.getElementById('photo-tab-btn')?.addEventListener('click', () => {
    if (!photoRenderer.isActive()) _photoModeEnter()
  })

  registerShortcut({
    key: 'p', ctrl: false, shift: false,
    description: 'Toggle photo mode',
    handler() {
      if (photoRenderer.isActive()) _photoModeExit()
      else _photoModeEnter()
    },
  })

  // Expose photo debug helpers on the existing debug object.
  if (window._nadocDebug) {
    window._nadocDebug.photoMaterials = function() {
      const s = photoRenderer.getSettings()
      console.group('[photo] active settings')
      console.log('active:', photoRenderer.isActive())
      console.log('lighting:', s.lighting)
      console.log('background:', s.bgType, s.bgColor)
      console.log('material presets:', { full: s.full, surface: s.surface, cylinders: s.cylinders, atomistic: s.atomistic })
      console.log('ssao:', s.ssao, '| bloom:', s.bloom, s.bloomStrength)
      console.log('pathTracing:', s.pathTracing, '| samples:', photoRenderer.getSampleCount())
      console.groupEnd()
      return s
    }
    window._nadocDebug.ptSamples = function() {
      const n = photoRenderer.getSampleCount()
      const building = photoRenderer.isPathTracingBuilding?.()
      const enabled  = photoRenderer.isPathTracingEnabled?.()
      console.log('[photo] path tracer — enabled:', enabled, '| building BVH:', building, '| samples:', n)
      return n
    }
    window._nadocDebug.ssaoParams = function() {
      const s = photoRenderer.getSettings()
      console.log('[photo] SSAO enabled:', s.ssao, '— kernelRadius≈0.3 nm, kernelSize=32, minDist=0.002, maxDist=0.12')
    }
    window._nadocDebug.bloomParams = function() {
      const s = photoRenderer.getSettings()
      console.log('[photo] bloom enabled:', s.bloom, '| strength:', s.bloomStrength)
    }
    window._nadocDebug.renderTargetSize = function() {
      const el = renderer.domElement
      console.log('[photo] main canvas:', el.width, '×', el.height, '| devicePixelRatio:', window.devicePixelRatio)
    }
  }

  return {
    enter: _photoModeEnter,
    exit: _photoModeExit,
    getExportRepActive: () => _exportRepActive,
    withExportRepresentation: _withExportRepresentation,
  }
}
