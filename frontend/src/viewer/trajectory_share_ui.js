import { prepareTrajectory } from './prepare_trajectory.js'
import { clipFrameAt } from './trajectory_clip.js'

export function mountTrajectoryShare({ dialog, prepared, store, getSource, document: doc = document }) {
  const field = doc.createElement('fieldset'); field.dataset.clipOptions = ''; field.className = 'sharing-card sharing-clip'
  field.innerHTML = `<legend><label class="sharing-check"><input type="checkbox" data-include-clip>Include recorded trajectory</label></legend><div data-clip-settings hidden><p class="sharing-description">Load and pause a NAMD trajectory in Full, VDW, ball-and-stick or stick view with water off. Atomic clips depend on structure size: 16 MiB per frame, 128 MiB per clip, maximum 120 samples. Start with 8 samples; guests can buffer before playback. Preparation restores your inspected frame.</p>
    <div class="sharing-fields"><label>First frame<input class="input" data-from type="number" min="1" value="1"></label><label>Last frame<input class="input" data-to type="number" min="2" value="8"></label><label>Interval<input class="input" data-step type="number" min="1" value="1"></label><label>Samples/s<select class="select" data-fps><option>4</option><option selected>8</option><option>15</option><option>30</option></select></label></div>
    <div class="sharing-actions"><button class="btn" data-cancel-clip disabled>Cancel preparation</button></div></div>`
  dialog.insertBefore(field, dialog.querySelector('[data-publish-actions]') ?? dialog.querySelector('[data-status]') ?? dialog.querySelector('[data-links]'))
  let abort = null
  const el = key => field.querySelector(`[data-${key}]`)
  el('include-clip').onchange = () => { el('clip-settings').hidden = !el('include-clip').checked }
  el('cancel-clip').onclick = () => abort?.abort()
  return { get enabled() { return el('include-clip').checked }, setBusy(value) { for (const input of field.querySelectorAll('input, select')) input.disabled = value }, async prepare(onProgress) {
    if (abort) throw new Error('Trajectory preparation is already running')
    abort = new AbortController(); el('cancel-clip').disabled = false
    try {
      if (doc.getElementById('menu-help-broadcast')?.getAttribute('aria-pressed') === 'true') throw new Error('Stop visualization broadcasting before preparing a trajectory clip')
      const source = getSource()
      if (!['full', 'vdw', 'ballstick', 'stick'].includes(source.representation)) throw new Error('Choose Full, VDW, ball-and-stick or stick before preparing a trajectory clip')
      return await prepareTrajectory({ prepared, store, source, from: Number(el('from').value) - 1, to: Number(el('to').value) - 1,
        step: Number(el('step').value), fps: Number(el('fps').value), signal: abort.signal, onProgress })
    } finally { abort = null; el('cancel-clip').disabled = true }
  }, dispose() { abort?.abort(); field.remove() } }
}

/** Host controls stay available while the editor privately inspects other files. */
export function appendTrajectoryControls({ section, share, api, status, document: doc = document }) {
  const clip = share.trajectory
  if (!clip) return
  const controls = doc.createElement('div'); controls.className = 'sharing-playback'
  controls.innerHTML = '<div class="sharing-actions"><button class="btn btn--primary" data-clip-play>Play shared clip</button><button class="btn" data-clip-pause>Pause shared clip</button></div><label class="sharing-seek">Shared clip frame<input data-clip-seek type="range" min="0" value="0" aria-label="Shared clip frame"></label>'
  section.append(controls)
  const slider = controls.querySelector('input'); slider.max = String(clip.count - 1)
  let pending = false
  async function command(playing, frame) {
    if (pending) return
    pending = true
    try {
      const latest = await api(`shares/${share.id}/trajectory`)
      if (frame == null) frame = clipFrameAt(latest.trajectory, latest.serverTime, clip.count)
      if (playing && frame === clip.count - 1) frame = 0
      const value = await api(`shares/${share.id}/trajectory`, { method: 'POST', body: JSON.stringify({ id: clip.id, frame, playing, fps: clip.fps }) })
      slider.value = String(value.trajectory.frame)
      status.textContent = playing ? 'Shared trajectory playing. Guests keep independent cameras.' : `Shared trajectory paused at clip sample ${frame + 1}.`
    } catch (error) { status.textContent = error.message }
    finally { pending = false }
  }
  controls.querySelector('[data-clip-play]').onclick = () => command(true, null)
  controls.querySelector('[data-clip-pause]').onclick = () => command(false, null)
  slider.onchange = () => command(false, Number(slider.value))
}
