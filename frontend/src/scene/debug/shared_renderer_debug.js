/** Installs the opt-in shared-renderer diagnostics and FPS sampler. */
export function installSharedRendererDebug({
  useShared, scene, camera, renderer, assemblyRenderer, store, THREE, controls,
  animateCameraTo, designRenderer, addFrameCallback, getUnfoldView,
  getActiveControls, api,
}) {
  if (!useShared) return null
  // ── Continuous-loop FPS tracker (path-to-thousands LOD benchmark) ───────
  // scene.js renders every frame via setAnimationLoop, so each frame-callback
  // tick == one on-screen frame.  We keep an EMA of instantaneous FPS for the
  // HUD plus per-frame draw-call / triangle counts (read from renderer.info,
  // which reflects the prior frame — off-by-one is negligible).  sampleFps()
  // turns on a fixed-duration capture window the automated sweep awaits.
  const _frameStats = {
    last: performance.now(), dt: 0, ema: 0, drawCalls: 0, triangles: 0,
    _samples: null,
  }
  addFrameCallback(() => {
    const now = performance.now()
    const dt = now - _frameStats.last
    _frameStats.last = now
    _frameStats.dt = dt
    const fps = dt > 0 ? 1000 / dt : 0
    _frameStats.ema = _frameStats.ema ? _frameStats.ema * 0.9 + fps * 0.1 : fps
    const ri = renderer.info.render
    _frameStats.drawCalls = ri.calls
    _frameStats.triangles = ri.triangles
    if (_frameStats._samples) _frameStats._samples.push(dt)
  })

  window.__NADOC_DBG__ = {
    scene, camera, renderer, assemblyRenderer, store, THREE, controls, animateCameraTo,
    designRenderer,
    get unfoldView() { return getUnfoldView() },

    // Crossover-tube validation metric — select a crossover, then call this to read
    // the LIVE tube geometry (sides / completeness / NaN). See getSelectionArcTubeStats.
    tubeStats: () => designRenderer.getSelectionArcTubeStats(),

    /**
     * Track-B diagnostic. Pre-conditions:
     *   1. window.NADOC_DBG_RENDER_TRACE = true   (BEFORE the assembly built)
     *   2. Reload the page and let the assembly finish loading.
     *
     * Then call __NADOC_DBG__.traceFrame() to render one frame with reset
     * counters and dump structured stats: total draw calls, triangles,
     * lines, per-shared-mesh onBeforeRender hit counts. Lets us see
     * whether the bp InstancedMeshes are actually being drawn each frame.
     */
    traceFrame() {
      if (renderer._nadocTrace) renderer._nadocTrace.clear()
      renderer.info.reset()
      renderer.render(scene, camera)
      const info = renderer.info
      console.log('--- traceFrame ---')
      console.log('renderer.info.render:', { ...info.render })
      console.log('renderer.info.memory:', { ...info.memory })
      console.log('renderer.info.programs.length:', info.programs?.length)
      if (renderer._nadocTrace && renderer._nadocTrace.size > 0) {
        console.log('Per-shared-mesh onBeforeRender hits this frame:')
        for (const [id, hits] of renderer._nadocTrace.entries()) {
          console.log(' ', id, '→', hits)
        }
      } else {
        console.log('No traces — was window.NADOC_DBG_RENDER_TRACE = true at rebuild time?')
      }
      // Also collect the shared meshes that should be drawn this frame
      const shared = []
      scene.traverse(o => {
        if (o.isInstancedMesh && o.count > 0 && o.material?.userData?.shader?.uniforms?.u_instanceXform) {
          shared.push({
            name: o.name || '(unnamed)',
            id: o.id,
            count: o.count,
            visible: o.visible,
            materialVisible: o.material.visible,
            frustumCulled: o.frustumCulled,
            parentVisible: o.parent?.visible,
          })
        }
      })
      console.log('Shared-renderer InstancedMeshes that COULD draw:', shared.length)
      shared.forEach(s => console.log(' ', s))
    },

    /**
     * Angular-LOD diagnostic.  Prints a table of every source's last-frame
     * bucket counts (close/mid/far), the pixel-size range across visible
     * instances, and the current closePx/farPx thresholds.  Run this
     * while zooming to see whether maxPxSize is crossing closePx (=60
     * by default).  If maxPxSize stays below closePx no matter how close
     * you zoom, the angular math has an upstream bug — call out
     * pxFactor / bboxDiag values.
     */
    probeLod() {
      const snap = assemblyRenderer.probeLod?.()
      if (!snap) { console.warn('[dbg] probeLod not exposed (shared path off?)'); return }
      console.log('--- LOD probe ---')
      console.log('thresholds:', { closePx: snap.closePx, farPx: snap.farPx })
      console.table(snap.sources)
      return snap
    },

    /**
     * Tune the angular-LOD thresholds without a reload.  Lower closePx
     * to make close-LOD trigger more easily; lower farPx to delay the
     * far billboard.  Example:
     *   __NADOC_DBG__.setLodThresholds({ closePx: 20, farPx: 4 })
     */
    setLodThresholds(opts) {
      assemblyRenderer.setLodThresholds?.(opts)
      console.log('[dbg] new thresholds applied:', opts)
    },

    /**
     * Toggleable on-canvas HUD that updates every frame with the current
     * LOD bucket counts + pixel-size range, per source.  Call once to
     * show; call again to hide.  Useful while zooming/panning to see
     * the bucket transitions live.
     */
    toggleLodHud() {
      if (window.__NADOC_LOD_HUD__) {
        window.__NADOC_LOD_HUD__.remove()
        window.__NADOC_LOD_HUD__ = null
        if (window.__NADOC_LOD_HUD_RAF__) {
          cancelAnimationFrame(window.__NADOC_LOD_HUD_RAF__)
          window.__NADOC_LOD_HUD_RAF__ = null
        }
        console.log('[dbg] LOD HUD off')
        return
      }
      const hud = document.createElement('div')
      hud.style.cssText = `
        position: fixed; top: 80px; right: 12px; z-index: 10000;
        background: rgba(13,17,23,0.88); color: #c9d1d9;
        padding: 8px 12px; border-radius: 6px;
        font-family: ui-monospace, monospace; font-size: 11px;
        line-height: 1.5; pointer-events: none;
        border: 1px solid #30363d; white-space: pre;
      `
      document.body.appendChild(hud)
      window.__NADOC_LOD_HUD__ = hud
      const tick = () => {
        const fpsLine = `${_frameStats.ema.toFixed(0)} fps  ${_frameStats.dt.toFixed(1)} ms  `
          + `${_frameStats.drawCalls} draws  ${(_frameStats.triangles / 1e3).toFixed(0)}k tris`
        const snap = assemblyRenderer.probeLod?.()
        if (!snap || snap.sources.length === 0) {
          hud.textContent = `LOD HUD\n${fpsLine}\n(no sources)`
        } else {
          const lines = [`LOD HUD  closePx=${snap.closePx}  farPx=${snap.farPx}`, fpsLine]
          for (const s of snap.sources) {
            const c = s.counts ?? { close: '-', mid: '-', far: '-', hull: '-' }
            const px = (s.minPxSize == null || s.maxPxSize == null)
              ? '(no data)'
              : `${s.minPxSize.toFixed(1)}…${s.maxPxSize.toFixed(1)} px`
            const key = s.srcKey.length > 28 ? s.srcKey.slice(-28) : s.srcKey
            lines.push(
              `${key}\n  N=${s.numInstances}  close=${c.close} mid=${c.mid} far=${c.far} hull=${c.hull ?? '-'}\n  pxSize=${px}  bboxDiag=${s.bboxDiag?.toFixed(0) ?? '?'}`,
            )
          }
          hud.textContent = lines.join('\n')
        }
        window.__NADOC_LOD_HUD_RAF__ = requestAnimationFrame(tick)
      }
      tick()
      console.log('[dbg] LOD HUD on (call toggleLodHud() again to dismiss)')
    },

    /** Live frame-stats snapshot: smoothed FPS, last frame ms, draw calls,
     *  triangles.  Cheap — read it any time. */
    fps() {
      return {
        fps: +_frameStats.ema.toFixed(1),
        frameMs: +_frameStats.dt.toFixed(2),
        drawCalls: _frameStats.drawCalls,
        triangles: _frameStats.triangles,
      }
    },

    /**
     * Collect a fixed-duration FPS sample window (default 2 s) and return a
     * Promise of summary stats.  The automated sweep awaits this AFTER it has
     * positioned the camera + let the LOD settle.  p5Fps is the 5th-percentile
     * (worst-case stutter) FPS — the number that decides whether a config is
     * actually smooth, not just smooth-on-average.
     */
    async sampleFps(durationMs = 2000) {
      _frameStats._samples = []
      await new Promise(r => setTimeout(r, durationMs))
      const dts = _frameStats._samples
      _frameStats._samples = null
      if (!dts || !dts.length) return { frames: 0 }
      const fpsArr = dts.map(d => 1000 / d).sort((a, b) => a - b)
      const q = p => fpsArr[Math.min(fpsArr.length - 1,
        Math.max(0, Math.floor(p * fpsArr.length)))]
      const avg = fpsArr.reduce((s, v) => s + v, 0) / fpsArr.length
      return {
        frames: dts.length,
        avgFps: +avg.toFixed(1),
        medianFps: +q(0.5).toFixed(1),
        p5Fps: +q(0.05).toFixed(1),
        minFps: +fpsArr[0].toFixed(1),
        drawCalls: renderer.info.render.calls,
        triangles: renderer.info.render.triangles,
      }
    },

    /**
     * Patch every assembly instance to one representation so the LOD ladder
     * is exercised at that rep.  full/beads → close-LOD eligible (cap 0);
     * cylinders → mid floor (cap 1); hull-prism → hull bucket (cap 3).
     * Returns the instance count.  Single batched PATCH → one renderer
     * rebuild (slow at scale for 'full' — that IS the cold-build cost).
     */
    async setAllRep(repr) {
      const insts = store.getState().currentAssembly?.instances ?? []
      if (!insts.length) { console.warn('[dbg] no assembly instances'); return 0 }
      await api.batchPatchInstances(insts.map(i => ({ id: i.id, representation: repr })))
      console.log(`[dbg] set ${insts.length} instances → '${repr}'`)
      return insts.length
    },

    /**
     * Multiscale-nav tuning handle (View → Orbit mode → Multiscale).
     *   __NADOC_DBG__.msNav.probe()                  → nearest helix, local scale, nm per notch
     *   __NADOC_DBG__.msNav.set({ zoomFrac, boost }) → live-tune the feel
     * No-ops (returns null) unless Multiscale is the active orbit mode.
     */
    msNav: {
      probe: () => getActiveControls().probeNavScale?.() ?? null,
      set:   p  => getActiveControls().setNavParams?.(p) ?? null,
      get:   () => getActiveControls().getNavParams?.() ?? null,
    },

    /**
     * Distance (nm) that frames the whole assembly to the viewport height.
     * margin > 1 zooms out a touch so nothing clips the edge.
     */
    fitDist(margin = 1.2) {
      const box = assemblyRenderer.getBoundingBox?.()
      if (!box || box.isEmpty()) return null
      const radius = box.getBoundingSphere(new THREE.Sphere()).radius
      const fov = camera.fov * Math.PI / 180
      return +(radius * margin / Math.tan(fov / 2)).toFixed(1)
    },

    /**
     * Place the camera at distance d (nm) from the assembly centre along the
     * current view direction, looking at the centre.  Reproducible framing
     * for the camera-distance sweep + manual runs.  Returns {radius, dist}.
     */
    setCameraDist(d, dirArr) {
      const box = assemblyRenderer.getBoundingBox?.()
      if (!box || box.isEmpty()) { console.warn('[dbg] no assembly bbox'); return null }
      const center = box.getCenter(new THREE.Vector3())
      const radius = box.getBoundingSphere(new THREE.Sphere()).radius
      const dir = Array.isArray(dirArr)
        ? new THREE.Vector3(dirArr[0], dirArr[1], dirArr[2])
        : camera.position.clone().sub(controls.target)
      if (dir.lengthSq() < 1e-9) dir.set(0, 0, 1)
      dir.normalize()
      camera.position.copy(center).add(dir.multiplyScalar(d))
      controls.target.copy(center)
      camera.near = Math.max(0.1, d - radius * 2)
      camera.far = d + radius * 4
      camera.updateProjectionMatrix()
      controls.update()
      return { radius: +radius.toFixed(1), dist: d }
    },
  }
  return window.__NADOC_DBG__
}
