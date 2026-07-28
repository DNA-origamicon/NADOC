/**
 * RunPod GPU picker — the "Check RunPod GPUs" button + scrollable results box in the
 * Clusters card. On click it polls the backend (`/runpod/gpu-options`, which fuses live
 * RunPod stock/prices with the learned per-arch throughput and the relax-ladder length) and
 * lists every available GPU with price, estimated relaxation time, and estimated cost.
 *
 * Rows are selectable; the chosen card is reported via `onSelect(row)` so the caller can
 * carry it into the job submission. Pure formatting/markup lives in `runpod_gpu_options.js`
 * (separately tested); this factory owns only the DOM + fetch + selection state.
 */
import { getRunpodGpuOptions } from '../api/client.js'
import {
  gpuOptionsHeader,
  gpuOptionsMessage,
  renderGpuOptionRows,
} from './runpod_gpu_options.js'

/**
 * @param {object}   deps
 * @param {Element}  deps.mount         container inside the Clusters card
 * @param {Function} deps.fetchOptions  () => Promise<resp> (injectable for tests)
 * @param {Function} deps.onSelect      called with the chosen GPU row (or null)
 */
export function initRunpodGpuPicker({
  mount,
  fetchOptions = getRunpodGpuOptions,
  onSelect = () => {},
} = {}) {
  let _resp = null
  let _busy = false
  let _selected = null

  function _render() {
    if (!mount) return
    const rows = _resp && _resp.ok ? renderGpuOptionRows(_resp.gpus, _selected) : ''
    const msg = gpuOptionsMessage(_resp, { busy: _busy })
    mount.innerHTML = `
      <button id="runpod-check-gpus-btn" ${_busy ? 'disabled' : ''} style="
        font-size:11px;padding:4px 10px;background:#161b22;border:1px solid #30363d;
        color:#c9d1d9;border-radius:4px;cursor:${_busy ? 'default' : 'pointer'}">
        ${_busy ? 'Checking RunPod…' : 'Check RunPod GPUs'}
      </button>
      ${
        rows
          ? `<div style="margin-top:6px;border:1px solid #30363d;border-radius:5px;overflow:hidden">
               ${gpuOptionsHeader()}
               <div style="max-height:180px;overflow-y:auto;display:flex;flex-direction:column;
                 gap:1px;font-size:10px;padding:2px">${rows}</div>
             </div>`
          : ''
      }
      ${
        msg
          ? `<div style="font-size:9px;color:#6e7681;margin-top:5px;line-height:1.35">${msg}</div>`
          : ''
      }
    `
    mount.querySelector('#runpod-check-gpus-btn')?.addEventListener('click', () => check())
    mount.querySelectorAll('.runpod-gpu-row').forEach(el => {
      const pick = () => _select(el.dataset.key)
      el.addEventListener('click', pick)
      el.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          pick()
        }
      })
    })
  }

  function _select(key) {
    _selected = key
    const row = (_resp?.gpus ?? []).find(g => g.key === key) || null
    onSelect(row)
    _render()
  }

  /** Poll RunPod for GPU options. Never throws — a failure renders as a message, not a crash. */
  async function check() {
    _busy = true
    _render()
    try {
      _resp = await fetchOptions()
    } catch {
      _resp = { ok: false, gpus: [], note: 'Backend unreachable.' }
    } finally {
      _busy = false
      _render()
    }
    return _resp
  }

  _render()

  return {
    check,
    get options() {
      return _resp
    },
    get selected() {
      return _selected
    },
    clear() {
      _resp = null
      _selected = null
      _render()
    },
  }
}
