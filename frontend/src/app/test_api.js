/** Install the dev-only browser automation facade used by Playwright. */
import * as THREE from 'three'
import { clientToNdc } from '../scene/ndc.js'
import { parseBaseKey } from '../scene/base_ref.js'

export function installTestApi({
  scene,
  store,
  visibilityController,
  designRenderer,
  _setRepresentation,
  controls,
  camera,
  canvas,
  renderer,
  oxdnaAnchorsSetup,
  _anchorSelectionState,
  atomisticRenderer,
  selectionManager,
  _nucleotideTransformTool,
  bluntEnds,
  slicePlane,
  _extrudePanel,
  assemblyRenderer,
  selectAssemblyClusterForTest,
  _assemblyPendingPartJoints,
  _assemblyPendingTransforms,
  _activateTranslateRotateTool,
  _clusterBackboneEntries,
  clusterGizmo,
  api,
  _enterAssemblyMode,
  _exitAssemblyMode,
  forceCrossoverTool,
}) {
  window.__nadocTest = {
    scene,
    store,
    /** Automation API for persisted visibility operations. These drive the
     * exact controller used by context menus and the spreadsheet. */
    visibility: {
      hideStrands: (strandIds) => visibilityController.hide({ strandIds }),
      showStrands: (strandIds) => visibilityController.show({ strandIds }),
      unhideAll: () => visibilityController.unhideAll(),
      undo: () => visibilityController.undo(),
      redo: () => visibilityController.redo(),
      hiddenBaseKeys: () => [...visibilityController.getHiddenBaseKeys()],
      flush: () => visibilityController.flushPersistence(),
      strandRenderStats(strandId) {
        const scale = new THREE.Vector3(), pos = new THREE.Vector3(), quat = new THREE.Quaternion()
        const stats = { beads: 0, visibleBeads: 0, cones: 0, visibleCones: 0, slabs: 0, visibleSlabs: 0 }
        for (const e of designRenderer.getBackboneEntries()) {
          if (e.nuc?.strand_id !== strandId) continue
          stats.beads++
          const m = new THREE.Matrix4(); e.instMesh.getMatrixAt(e.id, m); m.decompose(pos, quat, scale)
          if (scale.lengthSq() > 1e-10) stats.visibleBeads++
        }
        for (const e of designRenderer.getConeEntries()) {
          if (e.strandId !== strandId) continue
          stats.cones++
          const m = new THREE.Matrix4(); e.instMesh.getMatrixAt(e.id, m); m.decompose(pos, quat, scale)
          if (Math.abs(scale.x) > 1e-5 || Math.abs(scale.z) > 1e-5) stats.visibleCones++
        }
        for (const e of designRenderer.getSlabEntries()) {
          if (e.nuc?.strand_id !== strandId) continue
          stats.slabs++
          const m = new THREE.Matrix4(); e.instMesh.getMatrixAt(e.id, m); m.decompose(pos, quat, scale)
          if (scale.lengthSq() > 1e-10) stats.visibleSlabs++
        }
        return stats
      },
    },
    setRepresentation: (repr) => _setRepresentation(repr),
    controlsEnabled: () => controls.enabled,
    poisonCameraForTest() {
      camera.position.set(NaN, NaN, NaN)
      controls.target.set(NaN, NaN, NaN)
    },
    viewerDiagnostic() {
      const canvasRect = canvas.getBoundingClientRect()
      const hit = document.elementFromPoint(
        canvasRect.left + canvasRect.width / 2,
        canvasRect.top + canvasRect.height / 2,
      )
      const helixCtrl = designRenderer.getHelixCtrl()
      return {
        url: location.href,
        designId: store.getState().currentDesign?.id ?? null,
        geometryCount: store.getState().currentGeometry?.length ?? 0,
        backboneEntries: designRenderer.getBackboneEntries?.().length ?? 0,
        slabEntries: designRenderer.getSlabEntries?.().length ?? 0,
        hiddenBaseKeys: [...visibilityController.getHiddenBaseKeys()],
        cgRootExists: Boolean(helixCtrl?.root),
        cgRootVisible: Boolean(helixCtrl?.root?.visible),
        controlsEnabled: controls.enabled,
        camera: {
          position: camera.position.toArray(), target: controls.target.toArray(),
          near: camera.near, far: camera.far, fov: camera.fov,
        },
        canvas: {
          width: canvas.width, height: canvas.height,
          cssWidth: canvasRect.width, cssHeight: canvasRect.height,
        },
        webglContextLost: renderer.getContext().isContextLost(),
        centerHit: hit ? {
          tag: hit.tagName, id: hit.id, classes: hit.className,
          pointerEvents: getComputedStyle(hit).pointerEvents,
        } : null,
        welcomeHidden: document.getElementById('welcome-screen')?.classList.contains('hidden'),
        lastError: store.getState().lastError,
      }
    },
    /** Anchors: the oxDNA card + the purple-halo sprite count, so a console/e2e check can
     *  assert "added an anchor → it glows" without a field or a launched job. */
    anchors: {
      card: oxdnaAnchorsSetup,
      selection: _anchorSelectionState,
      glowCount: () => designRenderer.anchorGlowCount(),
    },
    /** Camera-pose count of the loaded design (build-primitives readiness check). */
    getDesignCameraPoseCount: () => (store.getState().currentDesign?.camera_poses?.length ?? 0),
    /** Render the loaded design through its saved poses → {gifBase64, posterDataUrl}.
     *  Used by the offline build-primitives pipeline; see scene/primitive_preview_capture.js. */
    capturePrimitivePreview: async (opts = {}) => {
      const { capturePosesGif } = await import('../scene/primitive_preview_capture.js')
      const poses = store.getState().currentDesign?.camera_poses ?? []
      return capturePosesGif({ renderer, scene, camera, controls, poses, ...opts })
    },
    getAtomisticRenderer: () => atomisticRenderer,
    isCGVisible: () => !!(designRenderer.getHelixCtrl()?.root?.visible),
    /** Live rendered crossover-insert geometry for Full/atomistic registration probes.
     * Reads InstancedMesh matrices on both sides; source placement/API coordinates are
     * deliberately not consulted. */
    getRenderedXoverExtraGeometry() {
      const out = {}
      const atomsByKey = new Map()
      atomisticRenderer.visitAtoms((atom, pos) => {
        if (atom.crossover_id == null || atom.extra_base_k == null) return
        const key = `${atom.crossover_id}:${atom.extra_base_k}`
        if (!atomsByKey.has(key)) atomsByKey.set(key, [])
        atomsByKey.get(key).push({ name: atom.name, element: atom.element, pos: pos.toArray() })
      })
      for (const entry of designRenderer.getXoverBeadEntries?.() ?? []) {
        const target = { helix_id: '__xb__', crossover_id: entry.xoId, k: entry.simK }
        const info = designRenderer.xoverResidueInfo?.(target)
        if (!info) continue
        const bead = new THREE.Vector3(), slab = new THREE.Vector3()
        const slabQ = new THREE.Quaternion(), slabScale = new THREE.Vector3()
        const connector = new THREE.Vector3(), connectorQ = new THREE.Quaternion()
        const connectorScale = new THREE.Vector3()
        info.beadMatrix.decompose(bead, new THREE.Quaternion(), new THREE.Vector3())
        info.slabMatrix.decompose(slab, slabQ, slabScale)
        info.slabConnectorMatrix?.decompose(connector, connectorQ, connectorScale)
        const key = `${entry.xoId}:${entry.simK}`
        out[key] = {
          crossoverId: entry.xoId, k: entry.simK,
          bead: bead.toArray(), slab: slab.toArray(),
          pointA: info.arcData?.pointA?.toArray() ?? null,
          pointB: info.arcData?.pointB?.toArray() ?? null,
          axisA: info.arcData?.nucA?.axis_tangent ?? null,
          axisB: info.arcData?.nucB?.axis_tangent ?? null,
          slabQuaternion: slabQ.toArray(), slabScale: slabScale.toArray(),
          slabConnector: info.slabConnectorMatrix ? connector.toArray() : null,
          slabConnectorQuaternion: info.slabConnectorMatrix ? connectorQ.toArray() : null,
          slabConnectorScale: info.slabConnectorMatrix ? connectorScale.toArray() : null,
          atoms: atomsByKey.get(key) ?? [],
        }
      }
      return out
    },
    /** Return cone entries (crossover connections) with screen {x, y} midpoints. */
    getConeScreenPositions() {
      const rect = canvas.getBoundingClientRect()
      const coneEntries = designRenderer.getConeEntries()
      const out = []
      for (const e of coneEntries) {
        if (!e.fromNuc || !e.toNuc) continue
        const fp = e.fromNuc.backbone_position
        const tp = e.toNuc.backbone_position
        const mid = new THREE.Vector3(
          (fp[0] + tp[0]) / 2, (fp[1] + tp[1]) / 2, (fp[2] + tp[2]) / 2,
        )
        const ndc = mid.clone().project(camera)
        out.push({
          x: rect.left + (ndc.x  *  0.5 + 0.5) * rect.width,
          y: rect.top  + (-ndc.y * 0.5 + 0.5) * rect.height,
          fromHelixId: e.fromNuc.helix_id,
          toHelixId:   e.toNuc.helix_id,
        })
      }
      return out
    },
    /** Screen {x,y} centres of up to `maxN` visible, on-screen backbone beads.
     *  Reusable primitive for gesture e2e tests (e.g. measurement_tool.spec.js). */
    getBackboneBeadScreenPositions(maxN = 12) {
      const rect = canvas.getBoundingClientRect()
      let mesh = null
      scene.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.visible && o.count > 0) mesh = o })
      if (!mesh) return []
      const m = new THREE.Matrix4(), v = new THREE.Vector3()
      const out = []
      const n = Math.min(maxN, mesh.count)
      for (let i = 0; i < n; i++) {
        mesh.getMatrixAt(i, m)
        v.setFromMatrixPosition(m).applyMatrix4(mesh.matrixWorld)
        const ndc = v.clone().project(camera)
        if (ndc.z > 1 || Math.abs(ndc.x) > 1 || Math.abs(ndc.y) > 1) continue  // behind camera / off-screen
        out.push({
          x: rect.left + (ndc.x  *  0.5 + 0.5) * rect.width,
          y: rect.top  + (-ndc.y * 0.5 + 0.5) * rect.height,
        })
      }
      return out
    },
    /** Visible overhang bead centres with canonical overhang identity. */
    getOverhangBeadScreenPositions() {
      const rect = canvas.getBoundingClientRect()
      const out = []
      const v = new THREE.Vector3(), m = new THREE.Matrix4()
      for (const e of designRenderer.getBackboneEntries?.() ?? []) {
        const overhangId = e.nuc?.overhang_id
        if (!overhangId || !e.instMesh?.visible) continue
        e.instMesh.getMatrixAt(e.id, m)
        v.setFromMatrixPosition(m).applyMatrix4(e.instMesh.matrixWorld)
        const ndc = v.clone().project(camera)
        if (ndc.z > 1 || Math.abs(ndc.x) > 1 || Math.abs(ndc.y) > 1) continue
        out.push({
          id: overhangId,
          x: rect.left + (ndc.x * 0.5 + 0.5) * rect.width,
          y: rect.top + (-ndc.y * 0.5 + 0.5) * rect.height,
        })
      }
      return out
    },
    /** Visible cluster-level click candidates, resolved by selection_manager policy. */
    getClusterBeadScreenPositions() {
      const rect = canvas.getBoundingClientRect()
      const out = []
      const v = new THREE.Vector3(), m = new THREE.Matrix4()
      for (const e of designRenderer.getBackboneEntries?.() ?? []) {
        if (!e.instMesh?.visible) continue
        const id = selectionManager.clusterIdForNucleotide?.(e.nuc)
        if (!id) continue
        e.instMesh.getMatrixAt(e.id, m)
        v.setFromMatrixPosition(m).applyMatrix4(e.instMesh.matrixWorld)
        const ndc = v.clone().project(camera)
        if (ndc.z > 1 || Math.abs(ndc.x) > 1 || Math.abs(ndc.y) > 1) continue
        out.push({
          id,
          x: rect.left + (ndc.x * 0.5 + 0.5) * rect.width,
          y: rect.top + (-ndc.y * 0.5 + 0.5) * rect.height,
        })
      }
      return out
    },
    /** Live matrix probe for the selected standard nucleotide's bead/slab pair. */
    getSelectedResidueArrangement() {
      const keys = (store.getState().selection?.items ?? [])
        .filter(ref => ref.kind === 'base').map(ref => ref.key)
      if (keys.length !== 1) return null
      const target = parseBaseKey(keys[0])
      const info = designRenderer.residueTransformInfo?.(target)
      if (!info?.slabMatrix) return null
      const bead = new THREE.Vector3().setFromMatrixPosition(info.beadMatrix)
      const slab = new THREE.Vector3().setFromMatrixPosition(info.slabMatrix)
      const savedPose = store.getState().currentDesign?.nucleotide_transforms?.find(t =>
        t.kind === 'base' && t.helix_id === target.helix_id && t.bp_index === target.bp_index &&
        t.direction === target.direction && (t.copy_k ?? 0) === (target.copy ?? 0))
      return {
        key: keys[0], bead: bead.toArray(), slab: slab.toArray(),
        offset: slab.clone().sub(bead).toArray(), distance: slab.distanceTo(bead),
        independentPose: !!info.slab?.independentPose,
        savedDisplayOffset: savedPose?.display_slab_offset ?? null,
      }
    },
    /** Live bead-to-slab offsets for every rendered standard nucleotide. */
    getResidueArrangements() {
      const out = {}
      for (const entry of designRenderer.getBackboneEntries?.() ?? []) {
        const nuc = entry.nuc
        if (!nuc?.helix_id || nuc.bp_index == null || !nuc.direction) continue
        const target = {
          helix_id: nuc.helix_id, bp_index: nuc.bp_index,
          direction: nuc.direction, copy: nuc.copy_k ?? nuc.copy ?? 0,
        }
        const info = designRenderer.residueTransformInfo?.(target)
        if (!info?.beadMatrix || !info?.slabMatrix) continue
        const bead = new THREE.Vector3().setFromMatrixPosition(info.beadMatrix)
        const slab = new THREE.Vector3().setFromMatrixPosition(info.slabMatrix)
        const key = `${target.helix_id}:${target.bp_index}:${target.direction}:${target.copy}`
        out[key] = { offset: slab.sub(bead).toArray() }
      }
      return out
    },
    getNucleotideTransformScreenState() {
      const state = _nucleotideTransformTool.debugState()
      if (!state.pivot) return state
      const rect = canvas.getBoundingClientRect()
      const p = new THREE.Vector3(...state.pivot).project(camera)
      return {
        ...state,
        screenPivot: {
          x: rect.left + (p.x * 0.5 + 0.5) * rect.width,
          y: rect.top + (-p.y * 0.5 + 0.5) * rect.height,
        },
      }
    },
    /** Screen {x,y} + strand-end identity of every visible 5′/3′ terminus bead.
     *  Gesture e2e for the End-level multi-select → forced-ligation ('x') flow:
     *  lets a spec pick a valid opposite-polarity pair on different strands and
     *  click each end deterministically. */
    getEndBeadScreenPositions() {
      const rect = canvas.getBoundingClientRect()
      const out = []
      const v = new THREE.Vector3(), m = new THREE.Matrix4()
      for (const e of designRenderer.getBackboneEntries?.() ?? []) {
        const nuc = e.nuc
        if (!nuc?.strand_id) continue
        if (!nuc.is_five_prime && !nuc.is_three_prime) continue
        if (!e.instMesh?.visible) continue
        e.instMesh.getMatrixAt(e.id, m)
        v.setFromMatrixPosition(m).applyMatrix4(e.instMesh.matrixWorld)
        const ndc = v.clone().project(camera)
        if (ndc.z > 1 || Math.abs(ndc.x) > 1 || Math.abs(ndc.y) > 1) continue
        out.push({
          x: rect.left + (ndc.x  *  0.5 + 0.5) * rect.width,
          y: rect.top  + (-ndc.y * 0.5 + 0.5) * rect.height,
          strand_id: nuc.strand_id,
          helix_id:  nuc.helix_id,
          bp_index:  nuc.bp_index,
          direction: nuc.direction,
          is_five_prime:  !!nuc.is_five_prime,
          is_three_prime: !!nuc.is_three_prime,
        })
      }
      return out
    },
    /** Screen {x,y} + identity of each visible blunt-end ring (gesture e2e for
     *  blunt-end / primitive-on-face flows). */
    getDomainEndScreenPositions: () =>
      bluntEnds.getEndScreenInfo?.(camera, canvas.getBoundingClientRect()) ?? [],
    /** Slice-plane mode snapshot (visible / placement / continuation). */
    getSliceState: () => ({
      visible: slicePlane.isVisible(),
      placement: slicePlane.isPlacement(),
      armed: slicePlane.isArmed(),
      continuation: slicePlane.isContinuation(),
      deformed: slicePlane.isDeformed(),
    }),
    /** Deterministic counterpart of Blunt end → Extrude for large-scene e2e tests.
     *  (Software-WebGL ring raycasts are too slow/flaky to be the recommendation oracle.) */
    openExtrudeAtEnd({ helixId, diskBp, openSide = 1, plane = 'XY' }) {
      _extrudePanel.activate('continuation', { plane })
      slicePlane.showAtEnd(helixId, diskBp, true, { defaultDirSign: openSide })
      const helix = store.getState().currentDesign?.helices?.find(h => h.id === helixId)
      if (helix?.grid_pos) slicePlane.selectCellForTest(...helix.grid_pos)
    },
    /** Count of Alt-picked measurement beads (the measurement tool's input). */
    getCtrlBeadCount: () => selectionManager.getCtrlBeads?.().length ?? 0,
    /** Count of committed canonical End refs (never measurement anchors). */
    getSelectedEndCount: () => (store.getState().selection?.items ?? []).filter(ref => ref.kind === 'end').length,
    /** Base-level pool — app-wide base keys (scene/base_ref.js). */
    getSelectedBaseKeys: () => selectionManager.getSelectedBaseKeys?.() ?? [],
    /** Every base-level pick candidate as {key, family} — proves a bead family is reachable. */
    getBaseCandidates: () => selectionManager.getBaseCandidates?.() ?? [],
    /** Canonical mature selection snapshot (renderer-independent, JSON-safe). */
    getCanonicalSelection: () => structuredClone(store.getState().selection),
    /** Multi-selection pools (cluster multi-select gesture e2e). */
    getMultiSelection: () => ({
      clusterIds: (store.getState().selection?.items ?? [])
        .filter(ref => ref.kind === 'cluster').map(ref => ref.id),
      strandIds:  (store.getState().selection?.items ?? [])
        .filter(ref => ref.kind === 'strand').map(ref => ref.id),
    }),
    /** Drill-v2 engaged selection level ('default'|'cluster'|'strand'|'domain'|'end'|'xover'|'base'). */
    getSelectionLevel: () => selectionManager.getSelectionLevel?.() ?? 'default',

    // ── Robust gesture harness (MapGrab-style controller) ──────────────────
    // pickBeadAt runs the REAL raycast (same camera + bead meshes the selection
    // manager uses) against client (viewport) coords, returning the frontmost
    // bead hit or null. This is occlusion-correct — it answers "what would a
    // click here actually hit?" — unlike projecting a point and hoping.
    pickBeadAt(clientX, clientY) {
      const rect = canvas.getBoundingClientRect()
      const ndc = new THREE.Vector2(
        ((clientX - rect.left) / rect.width) * 2 - 1,
        -((clientY - rect.top) / rect.height) * 2 + 1,
      )
      const ray = new THREE.Raycaster()
      ray.setFromCamera(ndc, camera)
      const entries = designRenderer.getBackboneEntries?.() ?? []
      const meshes = [...new Set(entries.map(e => e.instMesh))].filter(m => m && m.visible)
      if (!meshes.length) return null
      const hits = ray.intersectObjects(meshes)
      if (!hits.length) return null
      const hit = hits[0]
      const entry = entries.find(e => e.instMesh === hit.object && e.id === hit.instanceId)
      if (!entry) return null
      return {
        instanceId: hit.instanceId,
        strand_id: entry.nuc?.strand_id, helix_id: entry.nuc?.helix_id,
        bp_index: entry.nuc?.bp_index, direction: entry.nuc?.direction,
      }
    },
    /** Cluster identity under a client point using the same front-most bead raycast. */
    pickClusterAt(clientX, clientY) {
      const rect = canvas.getBoundingClientRect()
      const ray = new THREE.Raycaster()
      ray.setFromCamera(new THREE.Vector2(
        ((clientX - rect.left) / rect.width) * 2 - 1,
        -((clientY - rect.top) / rect.height) * 2 + 1,
      ), camera)
      const entries = designRenderer.getBackboneEntries?.() ?? []
      const meshes = [...new Set(entries.map(e => e.instMesh))].filter(mesh => mesh?.visible)
      const hit = ray.intersectObjects(meshes)[0]
      if (!hit) return null
      const entry = entries.find(e => e.instMesh === hit.object && e.id === hit.instanceId)
      return entry?.nuc ? selectionManager.clusterIdForNucleotide?.(entry.nuc) ?? null : null
    },

    // ── Assembly gesture harness (mirrors the design-view hooks above) ─────
    // Used by e2e/helpers/scene_harness.js to validate the assembly canvas
    // pointer handlers (_onAssemblyPointerDown / _onAssemblyClick) — part
    // selection, group click-through, joint pick. Dev-only, never shipped.

    /** Occlusion-correct "which instance is front-most at this client point?" — the
     *  REAL pick (same NDC + camera the click handler uses). null if nothing hit.
     *  This is the identity oracle the gesture harness scans + clicks through. */
    pickAssemblyInstanceAt(clientX, clientY) {
      const ndc = clientToNdc(clientX, clientY, canvas.getBoundingClientRect())
      const hit = assemblyRenderer.pickInstance?.(ndc, camera)
      return hit ? { id: hit.id } : null
    },
    /** Selection-state oracles the retry loops assert against. */
    getActiveInstanceId: () => store.getState().activeInstanceId ?? null,
    getMultiSelectedInstanceIds: () => store.getState().multiSelectedInstanceIds ?? [],
    getActiveGroupId:    () => store.getState().activeGroupId ?? null,
    isAssemblyActive:    () => !!store.getState().assemblyActive,
    /** Arm the part-joint cluster drag (Priority 2b in _onAssemblyPointerDown):
     *  set the selected cluster so a subsequent pointer-down on the instance
     *  starts a cluster rotation. This is the gesture's selection PREREQUISITE
     *  (normally a cluster re-click / panel select); the ring DRAG itself stays
     *  the real gesture under test. */
    selectAssemblyClusterForTest(instanceId, clusterId) {
      selectAssemblyClusterForTest(instanceId, clusterId)
    },
    /** Pending (uncommitted) part-joint rotations recorded by _onAssemblyDragUp.
     *  The observable for the part-joint drag gesture: each entry's joint_value
     *  is the rotated angle. */
    getAssemblyPendingPartJoints() {
      return [..._assemblyPendingPartJoints.entries()].map(([key, v]) => ({
        key, jointValue: v?.body?.joint_value ?? null,
      }))
    },
    /** Pending (uncommitted) PRIMARY instance transforms recorded by the
     *  Move/Rotate tool — both the panel-input path (_mrCommitInputs →
     *  _queueAssemblyPrimaryCommit) and the gizmo onCommit callback feed the
     *  same `_assemblyPendingTransforms` map. The observable the move-tool
     *  gate asserts against: one entry per moved instance, with the matrix's
     *  translation column so a test can check the move actually landed.
     *  Distinct from getAssemblyPendingPartJoints (which is joint rotation). */
    getAssemblyPendingTransforms() {
      return [..._assemblyPendingTransforms.entries()].map(([instanceId, mat]) => ({
        instanceId,
        translation: mat ? [mat.elements[12], mat.elements[13], mat.elements[14]] : null,
      }))
    },
    /** Activate the assembly Move/Rotate tool on the currently-active instance
     *  (the real entry point — same fn the right-click "Move/Rotate" menu item
     *  and the toolbar button call). Requires an instance already selected.
     *  Returns the resulting translateRotateActive flag so the gate can assert
     *  the tool armed. Async — the gizmo attach awaits a pivot refresh. */
    async activateAssemblyMoveTool() {
      await _activateTranslateRotateTool()
      return !!store.getState().translateRotateActive
    },
    /** Activate the DESIGN-mode Move/Rotate tool on a specific cluster (the real
     *  entry point — same fn the Rotate button / cluster-row click call, with the
     *  cluster pre-targeted). Returns the pivot-select's option values so a gate
     *  can assert the duplex root options appear. Used by the duplex rotation-point
     *  e2e (pivot dropdown must hold a non-centroid selection across the round-trip). */
    async activateDesignMoveTool(clusterId) {
      store.setState({ activeClusterId: clusterId })
      await _activateTranslateRotateTool(clusterId)
      const sel = document.getElementById('mr-pivot-sel')
      return {
        active: !!store.getState().translateRotateActive,
        pivotOptions: sel ? [...sel.options].map(o => o.value) : [],
        pivotValue: sel?.value ?? null,
      }
    },
    /** Read the current Move/Rotate pivot-select {value, options}. The observable
     *  for the "dropdown holds a root pivot" gate. */
    getMoveRotatePivotState() {
      const sel = document.getElementById('mr-pivot-sel')
      return {
        value: sel?.value ?? null,
        options: sel ? [...sel.options].map(o => o.value) : [],
      }
    },
    /** Move/Rotate gizmo geometry for a cluster: the rotation pivot the gizmo uses,
     *  the world position where the gizmo HANDLES render, and the cluster's current
     *  bead centroid (rendered positions). Lets an e2e assert the gizmo sits at its
     *  pivot and that a +45° step rotates the beads about that pivot. */
    getClusterGizmoState(clusterId) {
      const design = store.getState().currentDesign
      const cluster = design?.cluster_transforms?.find(c => c.id === clusterId)
      const entries = cluster ? _clusterBackboneEntries(cluster, design) : []
      let cx = 0, cy = 0, cz = 0
      for (const e of entries) { cx += e.pos.x; cy += e.pos.y; cz += e.pos.z }
      const n = entries.length || 1
      return {
        pivot:      clusterGizmo.getPivot?.() ?? null,
        gizmoPos:   clusterGizmo.getGizmoWorldPosition?.() ?? null,
        beadCount:  entries.length,
        beadCentroid: [cx / n, cy / n, cz / n],
        beads:      entries.map(e => [e.pos.x, e.pos.y, e.pos.z]),
      }
    },
    /** Enter assembly mode on the doc's current server assembly. The 'a'
     *  toggle was removed (real entry is opening/creating a .nass); this
     *  mirrors that path's two steps — fetch into currentAssembly, then
     *  _enterAssemblyMode (which attaches the canvas pointer handlers). */
    async enterAssemblyMode() {
      await api.getAssembly()
      _enterAssemblyMode()
    },
    /** Exit assembly mode (flips assemblyActive → false, firing the
     *  subscriber's tear-down: gizmo detach, renderer dispose, multi-box
     *  dispose, listener removal). Mirrors the real close/new-doc path's
     *  call to _exitAssemblyMode; used by e2e to exercise the cleanup. */
    exitAssemblyMode() {
      _exitAssemblyMode()
    },
    /** Deterministically frame the camera on the assembly's RENDERED geometry
     *  (the actual instance meshes, not their transform origins — the rod body
     *  is offset from a part's local origin). The auto-fit relies on the
     *  renderer's bounding box, which is empty for these instances and fires
     *  late, leaving the parts off-screen / under a side panel. Returns false
     *  if no instance geometry is in the scene yet. */
    frameAssemblyForTest() {
      const bbox = new THREE.Box3()
      let any = false
      scene.traverse(o => {
        if (o.userData?.assemblyInstance) {
          o.updateWorldMatrix(true, true)
          const b = new THREE.Box3().setFromObject(o)
          if (!b.isEmpty() && isFinite(b.min.x) && isFinite(b.max.x)) { bbox.union(b); any = true }
        }
      })
      if (!any) return false
      const center = bbox.getCenter(new THREE.Vector3())
      const size = bbox.getSize(new THREE.Vector3())
      // View the broad face: place the camera dominantly along the SMALLEST
      // bbox axis (the parts can be thin ribbons; an edge-on view makes the
      // raycast graze past them and pick nothing).
      const dims = [size.x, size.y, size.z]
      const minAxis = dims.indexOf(Math.min(...dims))
      const dist = Math.max(Math.max(...dims) * 0.85, 25)
      const off = [0.25, 0.25, 0.25]; off[minAxis] = 1.0
      camera.position.set(center.x + off[0] * dist, center.y + off[1] * dist, center.z + off[2] * dist)
      camera.lookAt(center)
      camera.updateMatrixWorld(true)
      if (controls) { controls.target.copy(center); controls.update() }
      return true
    },
  }
  // Force-Crossover tool gesture hook (activate / pickEnd / state) — see
  // scene/force_crossover_tool.js. Lets e2e drive a forced ligation by strand id.
  window.__nadocForceXover = forceCrossoverTool.testApi
}
