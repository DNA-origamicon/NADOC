/**
 * Animation text overlay — DOM caption rendered above the canvas during
 * animation playback.
 *
 * The overlay is a single absolutely-positioned <div> appended to the
 * canvas's parent (#canvas-area).  It is updated each tick by the player
 * via the onTextOverlayUpdate callback.
 *
 * State payload (from animation_player.js):
 *   { text, fontFamily, fontSizePx, color, bold, italic, align, opacity }
 *   or null to hide.
 */

let _container = null
let _el        = null

function _ensure(container) {
  if (_el && _container === container) return _el
  _container = container
  _el = document.createElement('div')
  _el.id = 'anim-text-overlay'
  _el.style.cssText = [
    'position:absolute;left:0;right:0;bottom:40px',
    'pointer-events:none;user-select:none',
    'padding:0 32px;box-sizing:border-box',
    // Soft shadow so light text remains readable on bright backgrounds.
    'text-shadow:0 1px 3px rgba(0,0,0,0.7),0 0 8px rgba(0,0,0,0.5)',
    'opacity:0;display:none',
    'word-wrap:break-word;white-space:pre-wrap',
    'line-height:1.2',
    'z-index:5',
  ].join(';')
  // Container must be position:relative for absolute child to anchor; #canvas-area
  // already is in our layout, but set it defensively without overriding existing.
  if (container && getComputedStyle(container).position === 'static') {
    container.style.position = 'relative'
  }
  container.appendChild(_el)
  return _el
}

/**
 * Apply the overlay state, or hide if state is null.
 *
 * @param {HTMLElement} container — element the overlay is anchored inside
 *                                  (must be position:relative)
 * @param {object|null} state
 */
export function applyAnimationTextOverlay(container, state) {
  const el = _ensure(container)
  if (!state || !state.text) {
    el.style.display = 'none'
    el.style.opacity = '0'
    return
  }
  el.textContent       = state.text
  el.style.display     = ''
  el.style.opacity     = String(state.opacity ?? 1)
  el.style.fontFamily  = state.fontFamily ?? 'sans-serif'
  el.style.fontSize    = `${state.fontSizePx ?? 24}px`
  el.style.color       = state.color ?? '#ffffff'
  el.style.fontWeight  = state.bold   ? '700'    : '400'
  el.style.fontStyle   = state.italic ? 'italic' : 'normal'
  el.style.textAlign   = state.align  ?? 'center'
}
