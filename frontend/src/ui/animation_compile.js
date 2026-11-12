import { initCompiledKeyframeStatus } from './compiled_keyframe_status.js'
import { createPresentationLibrary } from '../scene/presentation_library.js'
import { initPresentationLibraryDialog } from './presentation_library_dialog.js'
import { compileIcon } from './compile_icon.js'
import { presentationSourceHash } from '../scene/presentation_package.js'
import { initCompiledPresentationPlayer } from './compiled_presentation_player.js'
import { sameFeatureSource } from '../scene/feature_animation_sequence.js'
import { compilePresentation } from '../scene/compile_presentation.js'
import { compilationEstimate, presentationHTML } from '../scene/compiled_presentation.js'
import './animation_compile.css'

export function initAnimationCompile({ anchor, player, renderer, scene, camera, getAnimation, beforeCompile, controls, captureCamera, getSource = () => null, getPlayOptions = () => ({}),
  onCompiledStatus = () => {}, compile = compilePresentation, library = createPresentationLibrary() }) {
  const root = document.createElement('div')
  root.className = 'animation-compile'
  root.innerHTML = `<div class="compile-actions"><button id="anim-compile-presentation-btn" class="btn">${compileIcon} Pre-compile</button>
    <button class="btn compile-open" title="Load a compiled presentation">Load</button></div>
    <label>Video size <select aria-label="Compiled video size"><option value="1080p">1080p</option><option value="720p">720p</option></select></label>
    <p class="compile-summary" role="status"></p>
    <div class="compile-result" hidden><button class="btn compile-play">Play compiled</button> <a class="compile-download">Download offline presentation</a></div>
    <div class="compile-preview-result" hidden><button class="btn compile-preview-play">Play compiled keyframe</button> <a class="compile-preview-download">Download keyframe</a></div>
    <dialog aria-label="Compiling presentation"><h3>Compiling presentation</h3><p>Preparing videos for offline playback. Keep this tab open. Single-file limit: 256 MiB of video.</p>
    <progress max="1" aria-label="Overall compilation progress"></progress><p class="compile-stage" role="status"></p><div class="compile-videos"></div><button class="btn compile-cancel">Cancel</button></dialog>`
  anchor?.after(root)
  const button = root.querySelector('button'), dialog = root.querySelector('dialog')
  const stage = root.querySelector('.compile-stage'), overall = root.querySelector('progress')
  const summary = root.querySelector('.compile-summary'), result = root.querySelector('.compile-result')
  const download = root.querySelector('a'), resolution = root.querySelector('select')
  let controller = null, url = null, signature = null, sourceSignature = null
  let compiled = null, preview = null
  const livePlayer = controls && camera ? initCompiledPresentationPlayer({
    viewport: document.getElementById('canvas-area') ?? renderer.domElement.parentElement,
    player, camera, controls, captureCamera, getPlayOptions, beforeStart: beforeCompile,
    sameDocument: data => (data.sourceId ?? data.source?.id) === getSource()?.id,
    isCurrent: async data => {
      if (data.sourceHash) return data.sourceId === getSource()?.id && data.sourceHash === await presentationSourceHash(getSource())
      return !!data.source && sameFeatureSource(data.source, getSource()) && data.signature === fingerprint()
    },
  }) : null
  const indicators = new Map()
  let compiledStates = new Map()
  const paintIndicator = (node, state = 'none') => {
    node.dataset.compiled = state
    node.textContent = state === 'ready' ? '✓' : state === 'stale' ? '↻' : state === 'checking' ? '…' : '○'
    node.title = state === 'ready' ? 'Matching pre-compiled video available' : state === 'stale' ? 'Keyframe or source changed — pre-compile again' : 'No matching compiled video loaded'
    node.setAttribute('aria-label', node.title)
    node.style.color = state === 'ready' ? '#3fb950' : state === 'stale' ? '#d29922' : '#8b949e'
  }
  const compiledStatus = initCompiledKeyframeStatus({ getAnimation, getSource, onChange: states => {
    compiledStates = states
    for (const [id, node] of indicators) paintIndicator(node, states.get(id))
    onCompiledStatus(states)
  } })
  let started = 0, currentIndex = -1, rows = [], bakeStage = null, bakeStarted = 0
  const fingerprint = () => JSON.stringify(getAnimation())
  const cancel = () => { if (!controller) return; controller.abort(); player.cancelBake?.(); stage.textContent = 'Cancelling…' }
  function refresh() {
    void compiledStatus.refresh()
    button.disabled = !!controller || !getAnimation()?.keyframes?.length
    if (controller && fingerprint() !== sourceSignature) cancel()
    if (url && signature != null && signature !== fingerprint()) summary.textContent = 'Animation changed. The compiled file is the previous version; compile again to update it.'
  }
  function progress(event) {
    if (event.phase === 'prepare') { overall.removeAttribute('value'); stage.textContent = 'Preparing scenes and trajectories · ETA available after measured progress'; return }
    if (event.phase === 'package') { stage.textContent = 'Packaging offline presentation…'; return }
    const row = rows[event.index]
    if (!row) return
    if (currentIndex !== event.index) { currentIndex = event.index; started = performance.now() }
    const seconds = compilationEstimate(event.done, event.frames, performance.now() - started)
    const eta = seconds == null ? 'ETA estimating…' : `ETA ~${seconds < 60 ? seconds + ' s' : Math.ceil(seconds / 60) + ' min'}`
    stage.textContent = `Video ${event.index + 1} of ${event.total}: ${event.name}`
    if (event.phase === 'capture') {
      row.bar.value = event.frames ? event.done / event.frames : 0
      row.text.textContent = `${event.done}/${event.frames} frames · ${eta}`
      overall.value = (event.index + row.bar.value) / event.total
    } else if (event.phase === 'encode') row.text.textContent = 'Finalizing video · ETA estimating…'
    else if (event.phase === 'complete') { row.bar.value = 1; row.text.textContent = 'Ready'; overall.value = (event.index + 1) / event.total }
  }
  async function start(keyframeId = null) {
    if (controller || !getAnimation()?.keyframes?.length) return
    livePlayer?.close()
    beforeCompile?.()
    const animation = structuredClone(getAnimation())
    const target = keyframeId == null ? null : animation.keyframes.find(kf => kf.id === keyframeId)
    if (keyframeId != null && !target?.trajectory_job_id) return
    const source = getSource(), initialCamera = captureCamera?.()
    let prepared = null
    sourceSignature = fingerprint(); currentIndex = -1; bakeStage = null; bakeStarted = performance.now()
    controller = new AbortController()
    refresh()
    const list = root.querySelector('.compile-videos'); list.replaceChildren()
    rows = (target ? [target] : animation.keyframes).map((kf, i) => {
      const item = document.createElement('div'), label = document.createElement('div'), bar = document.createElement('progress'), text = document.createElement('small')
      label.textContent = `${i + 1}. ${kf.name || kf.text || 'Keyframe'}`; bar.max = 1; bar.value = 0
      bar.setAttribute('aria-label', `Video ${i + 1} progress`); text.textContent = 'Queued'
      item.append(label, bar, text); list.append(item); return { bar, text }
    })
    dialog.showModal()
    try {
      const inspection = { sourceId: source?.id, sourceHash: await presentationSourceHash(source), initialCamera }
      controller.signal.throwIfAborted()
      const blob = await compile({ animation, keyframeId, player, renderer, scene, camera, resolution: resolution.value, playOptions: getPlayOptions(), inspection, onPrepared: data => { prepared = data }, signal: controller.signal, onProgress: progress })
      controller.signal.throwIfAborted()
      stage.textContent = 'Saving to the presentation library…'
      const saved = await library.save(blob, target?.name || (target ? `${animation.name || 'Presentation'} · trajectory keyframe` : animation.name || 'Presentation'), target ? 'keyframe' : 'presentation', controller.signal)
      controller.signal.throwIfAborted()
      compiledStatus.record(prepared)
      if (target) {
        if (preview) URL.revokeObjectURL(preview.url)
        preview = { url: URL.createObjectURL(blob), compiled: prepared && { ...prepared, source, signature: sourceSignature } }
        const link = root.querySelector('.compile-preview-download')
        link.href = preview.url; link.download = `${(target.name || 'trajectory-keyframe').replace(/[^\p{L}\p{N} _-]/gu, '_')}.html`
        root.querySelector('.compile-preview-result').hidden = false
        summary.textContent = `Keyframe ready. Play compiled keyframe to review it; the full presentation is unchanged. ${saved.notice}`
        return
      }
      if (url) URL.revokeObjectURL(url)
      url = URL.createObjectURL(blob); signature = sourceSignature
      compiled = prepared && { ...prepared, initialCamera, source, signature }
      download.href = url; download.download = `${(animation.name || 'presentation').replace(/[^\p{L}\p{N} _-]/gu, '_')}.html`
      result.hidden = false
      summary.textContent = `Ready · ${(blob.size / 1048576).toFixed(1)} MiB. ${saved.notice} No server or Wi-Fi needed for the downloaded file.`
    } catch (error) {
      summary.textContent = error.name === 'AbortError' ? 'Compilation cancelled. No incomplete file was saved.' : `Compilation failed: ${error.message}`
    } finally {
      controller = null; dialog.close(); refresh()
    }
  }
  const libraryDialog = initPresentationLibraryDialog({ root, library, onOpen(data, entry, notice) {
    livePlayer?.close()
    const blob = new Blob([presentationHTML(data.title || 'Presentation', data.clips, data.inspection)], { type: 'text/html' })
    if (url) URL.revokeObjectURL(url)
    url = URL.createObjectURL(blob); compiled = data.inspection; signature = null
    compiledStatus.record(data.inspection)
    download.href = url; download.download = `${entry.name.replace(/[^\p{L}\p{N} _-]/gu, '_')}.html`
    result.hidden = false
    summary.textContent = `Presentation opened. ${notice} Load the matching source document to inspect in 3D.`
  } })
  root.querySelector('.compile-open').onclick = () => { if (!controller) void libraryDialog.open() }
  button.addEventListener('click', () => start())
  root.querySelector('.compile-preview-play').onclick = () => {
    if (livePlayer && preview?.compiled) livePlayer.open(preview.url, preview.compiled)
    else if (preview) window.open(preview.url, '_blank', 'noopener')
  }
  root.querySelector('.compile-cancel').addEventListener('click', cancel)
  dialog.addEventListener('cancel', event => { event.preventDefault(); cancel() })
  root.querySelector('.compile-play').addEventListener('click', () => {
    if (livePlayer && compiled) livePlayer.open(url, compiled)
    else window.open(url, '_blank', 'noopener')
  })
  refresh()
  return { start, refresh,
    keyframeIndicator(kf) {
      const node = document.createElement('span')
      node.dataset.role = 'keyframe-compiled-status'
      node.style.cssText = 'font-size:12px;width:14px;flex-shrink:0;text-align:center'
      indicators.set(kf.id, node); paintIndicator(node, compiledStates.get(kf.id))
      return node
    },
    keyframeButton(kf) {
      const button = document.createElement('button')
      button.className = 'btn compile-keyframe'; button.innerHTML = compileIcon
      button.title = 'Compile this trajectory keyframe'; button.setAttribute('aria-label', button.title)
      button.disabled = !kf.trajectory_job_id
      button.onclick = event => { event.stopPropagation(); void start(kf.id) }
      return button
    },
    onPlayerEvent(event) {
      if (!controller) return livePlayer?.onPlayerEvent(event) ?? false
      if (event.type === 'baking_progress') {
        const done = event.done ?? event.current, total = event.total
        if (bakeStage !== event.stage) { bakeStage = event.stage; bakeStarted = performance.now() }
        const seconds = compilationEstimate(done, total, performance.now() - bakeStarted)
        const eta = seconds == null ? 'ETA estimating…' : `Stage ETA ~${Math.ceil(seconds / 60)} min`
        stage.textContent = `${event.label || 'Preparing scenes and trajectories'}${total > 0 ? ` · ${done ?? 0}/${total}` : ''} · ${eta}`
      }
      if (event.type === 'baking_cancelled') controller.abort()
      return true
    },
    dispose() { compiledStatus.dispose(); indicators.clear(); libraryDialog.dispose(); livePlayer?.dispose(); cancel(); if (url) URL.revokeObjectURL(url); if (preview) URL.revokeObjectURL(preview.url); root.remove() },
  }
}
