/** Wire the developer-facing render diagnostics menu. */
export function initDebugMenu({
  THREE,
  camera,
  canvas,
  controls,
  designRenderer,
  docHeaders,
  getJointRenderer,
  setMenuToggle,
  showToast,
  store,
}) {
  document.getElementById('menu-debug-lod-hud')?.addEventListener('click', function () {
    if (!window.__NADOC_DBG__?.toggleLodHud) {
      showToast(
        'Shared renderer not active — set localStorage.NADOC_SHARED_RENDERER = "true" then reload.',
        { severity: 'warn' },
      )
      return
    }
    window.__NADOC_DBG__.toggleLodHud()
    this.textContent = window.__NADOC_LOD_HUD__ ? 'Hide LOD HUD' : 'Show LOD HUD'
  })

  let hullClusterDebugOn = false
  document.getElementById('menu-debug-hull-cluster')?.addEventListener('click', function () {
    hullClusterDebugOn = !!getJointRenderer()?.setHullClusterDebug(!hullClusterDebugOn)
    this.textContent = hullClusterDebugOn ? 'Hide Hull Cluster Debug' : 'Show Hull Cluster Debug'
    if (hullClusterDebugOn) {
      showToast(
        'Hull Cluster Debug on — visible in the Hull Prism representation (View → Representation).',
        { severity: 'info' },
      )
    }
  })

  const renderFlags = { wireframe: false, doubleSide: false, opaque: false }
  function applyRenderDebug() {
    const root = designRenderer.getHelixCtrl()?.root
    if (!root) {
      showToast('No design geometry to debug.', { severity: 'error' })
      return
    }
    root.traverse(object => {
      const materials = object.material
        ? (Array.isArray(object.material) ? object.material : [object.material])
        : []
      for (const material of materials) {
        if (material.userData._dbgOrig === undefined) {
          material.userData._dbgOrig = {
            wireframe: material.wireframe,
            side: material.side,
            transparent: material.transparent,
          }
        }
        const original = material.userData._dbgOrig
        material.wireframe = renderFlags.wireframe ? true : original.wireframe
        material.side = renderFlags.doubleSide ? THREE.DoubleSide : original.side
        material.transparent = renderFlags.opaque ? false : original.transparent
        material.needsUpdate = true
      }
    })
  }

  for (const [id, flag] of [
    ['menu-debug-wireframe', 'wireframe'],
    ['menu-debug-doubleside', 'doubleSide'],
    ['menu-debug-opaque', 'opaque'],
  ]) {
    document.getElementById(id)?.addEventListener('click', () => {
      renderFlags[flag] = !renderFlags[flag]
      setMenuToggle(id, renderFlags[flag])
      applyRenderDebug()
    })
  }

  document.getElementById('menu-debug-copy-camera')?.addEventListener('click', () => {
    const position = camera.position
    const target = controls.target
    const text = [position.x, position.y, position.z, target.x, target.y, target.z]
      .map(value => value.toFixed(3))
      .join(',')
    navigator.clipboard?.writeText(text).catch(() => {})
    showToast(`Camera copied (pos.xyz,target.xyz): ${text}`, { duration: 7000 })
  })

  let inspectEnabled = false
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  const sideNames = { 0: 'FrontSide', 1: 'BackSide', 2: 'DoubleSide' }
  document.getElementById('menu-debug-inspect')?.addEventListener('click', () => {
    inspectEnabled = !inspectEnabled
    setMenuToggle('menu-debug-inspect', inspectEnabled)
    showToast(inspectEnabled
      ? 'Inspect Mesh ON — click a mesh to report it (console.table for full props).'
      : 'Inspect Mesh off')
  })
  canvas.addEventListener('click', event => {
    if (!inspectEnabled) return
    const root = designRenderer.getHelixCtrl()?.root
    if (!root) return
    const rect = canvas.getBoundingClientRect()
    pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    )
    raycaster.setFromCamera(pointer, camera)
    const hit = raycaster.intersectObject(root, true).find(result => result.object.visible)
    if (!hit) {
      showToast('Inspect: nothing under cursor')
      return
    }
    const object = hit.object
    const material = Array.isArray(object.material) ? object.material[0] : object.material
    const info = {
      name: object.name || '(unnamed)',
      objType: object.type,
      instanced: !!object.isInstancedMesh,
      count: object.isInstancedMesh ? object.count : undefined,
      geometry: object.geometry?.type,
      indexed: !!object.geometry?.index,
      vertices: object.geometry?.attributes?.position?.count,
      material: material?.type,
      side: sideNames[material?.side],
      transparent: material?.transparent,
      opacity: material?.opacity,
      depthWrite: material?.depthWrite,
      wireframe: material?.wireframe,
      frustumCulled: object.frustumCulled,
    }
    console.table(info)
    showToast(
      `${info.name} · ${info.geometry} · ${info.material} · ${info.side} · `
      + `transp=${info.transparent} op=${info.opacity} · fc=${info.frustumCulled}`,
      { duration: 9000 },
    )
  })

  document.getElementById('menu-debug-mrdna-roundtrip')?.addEventListener('click', async () => {
    if (!store.getState().currentDesign) {
      showToast('No design loaded.', { severity: 'error' })
      return
    }
    const button = document.getElementById('menu-debug-mrdna-roundtrip')
    const originalText = button.textContent
    button.textContent = 'Running… (may take ~10 s)'
    button.disabled = true
    try {
      const response = await fetch('/api/design/debug/mrdna-roundtrip', { headers: docHeaders() })
      if (!response.ok) {
        showToast(`Round-trip test failed:\n${await response.text()}`, { severity: 'error' })
        return
      }
      const blob = await response.blob()
      const match = (response.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = match ? match[1] : 'roundtrip.zip'
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      showToast(`Round-trip test error: ${error.message}`, { severity: 'error' })
    } finally {
      button.textContent = originalText
      button.disabled = false
    }
  })
}
