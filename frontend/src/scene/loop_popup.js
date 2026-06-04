/**
 * Circular-staple (loop) warning popup extracted from main.js. When the user
 * selects a red circular staple (no free 5'/3' ends), it offers a one-click nick
 * at the midpoint of the strand's longest domain. The nick-position math is the
 * pure `bestLoopNick`; the factory `initLoopPopup` owns the overlay DOM + the
 * store subscription + the api.addNick call. Unit-tested in loop_popup.test.js.
 */

/**
 * Best nick position for a circular staple: midpoint of the longest domain that
 * is ≥15 bp (so ≥7 bp sits on either side of the nick). Falls back to the
 * longest domain ≥3 bp if none qualify. Returns { helixId, bpIndex, direction }
 * or null. Pure.
 */
export function bestLoopNick(strand) {
  let bestNick = null
  let bestLen  = -1
  for (const domain of strand?.domains ?? []) {
    const lo  = Math.min(domain.start_bp, domain.end_bp)
    const hi  = Math.max(domain.start_bp, domain.end_bp)
    const len = hi - lo + 1
    if (len < 15) continue   // need ≥7+1+7 bp to safely nick
    const midBp = lo + Math.floor(len / 2)   // nick at midpoint
    if (len > bestLen) {
      bestLen  = len
      bestNick = { helixId: domain.helix_id, bpIndex: midBp, direction: domain.direction }
    }
  }
  if (!bestNick) {
    // Fallback: longest domain regardless of minimum spacing.
    for (const domain of strand?.domains ?? []) {
      const lo  = Math.min(domain.start_bp, domain.end_bp)
      const hi  = Math.max(domain.start_bp, domain.end_bp)
      const len = hi - lo + 1
      if (len > bestLen && len >= 3) {
        bestLen  = len
        bestNick = { helixId: domain.helix_id, bpIndex: lo + Math.floor(len / 2), direction: domain.direction }
      }
    }
  }
  return bestNick
}

/**
 * Wire the loop-strand popup. Self-subscribes to selection changes; shows the
 * overlay when a circular staple is selected and (on confirm) calls api.addNick.
 *
 * @param {object} deps
 * @param {object} deps.store        app store ({ subscribe, getState })
 * @param {object} deps.api          design api ({ addNick })
 * @param {() => boolean} deps.isCtrlHeld  suppress the popup while Ctrl is down
 * @returns {{ close: () => void, overlay: HTMLElement }}
 */
export function initLoopPopup({ store, api, isCtrlHeld }) {
  const overlay = document.createElement('div')
  overlay.id = 'loop-strand-popup'
  overlay.style.cssText = [
    'display:none', 'position:fixed', 'inset:0',
    'background:rgba(0,0,0,0.5)', 'z-index:1000',
    'align-items:center', 'justify-content:center',
  ].join(';')
  overlay.style.display = 'none'   // explicit (jsdom doesn't reflect it from cssText)
  overlay.innerHTML = `
    <div style="background:#1e2a3a;border:1px solid #ff3333;border-radius:8px;padding:24px 28px;max-width:380px;color:#e8eef4;font-family:var(--font-ui);">
      <p style="margin:0 0 8px;font-size:13px;color:#ff6b6b;font-weight:bold;">⚠ Circular staple detected</p>
      <p style="margin:0 0 18px;font-size:12px;line-height:1.5;">
        This staple strand has no free 5′/3′ ends.
        Nick automatically at the midpoint of its longest domain,
        or dismiss to leave it unresolved.
      </p>
      <div style="display:flex;gap:10px;justify-content:flex-end;">
        <button id="loop-popup-leave" style="padding:6px 14px;background:#2d3f52;border:1px solid #445566;border-radius:4px;color:#e8eef4;cursor:pointer;font-family:var(--font-ui);font-size:12px;">Leave unresolved</button>
        <button id="loop-popup-nick" style="padding:6px 14px;background:#c0392b;border:none;border-radius:4px;color:#fff;cursor:pointer;font-family:var(--font-ui);font-size:12px;">Nick here</button>
      </div>
    </div>
  `
  document.body.appendChild(overlay)

  let _pendingNick = null  // { helixId, bpIndex, direction }

  function close() {
    overlay.style.display = 'none'
    _pendingNick = null
  }

  overlay.querySelector('#loop-popup-leave').addEventListener('click', close)
  overlay.querySelector('#loop-popup-nick').addEventListener('click', async () => {
    const nick = _pendingNick
    close()
    if (!nick) return
    const result = await api.addNick(nick)
    if (!result) {
      const err = store.getState().lastError
      console.error('Loop nick failed:', err?.message)
    }
  })
  overlay.addEventListener('click', e => { if (e.target === overlay) close() })

  store.subscribe((newState, prevState) => {
    if (newState.selectedObject === prevState.selectedObject) return
    if (isCtrlHeld?.()) return
    const obj = newState.selectedObject
    if (!obj?.data?.strand_id) return
    const loopSet = new Set(newState.loopStrandIds ?? [])
    if (!loopSet.has(obj.data.strand_id)) return

    const strand = newState.currentDesign?.strands?.find(s => s.id === obj.data.strand_id)
    if (!strand) return

    _pendingNick = bestLoopNick(strand)
    overlay.style.display = 'flex'
  })

  return { close, overlay }
}
