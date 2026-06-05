import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initSyncBadge } from './sync_badge.js'

/**
 * The badge queries `#sync-status .sync-dot` (descendant combinator), the
 * `#sync-status-text` label, the `#sync-debug-panel` overlay, its `#sync-debug-close`
 * button and the `#sync-debug-body` log container. mountIds can't express the nested
 * dot, so build the DOM by hand.
 */
function mountBadgeDom() {
  document.body.innerHTML = `
    <div id="sync-status"><span class="sync-dot"></span></div>
    <span id="sync-status-text"></span>
    <div id="sync-debug-panel">
      <button id="sync-debug-close"></button>
      <div id="sync-debug-body"></div>
    </div>
  `
}

describe('initSyncBadge', () => {
  beforeEach(() => { mountBadgeDom() })
  afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })

  describe('setSyncStatus', () => {
    it('sets the dot state class and a timestamped label', () => {
      const badge = initSyncBadge()
      badge.setSyncStatus('green', 'saved')
      expect(document.querySelector('#sync-status .sync-dot').className).toBe('sync-dot green')
      const txt = document.getElementById('sync-status-text').textContent
      expect(txt).toMatch(/^saved \d{2}:\d{2}:\d{2}$/)
    })

    it('overwrites a prior state class (no accumulation)', () => {
      const badge = initSyncBadge()
      badge.setSyncStatus('yellow', 'saving…')
      badge.setSyncStatus('red', 'save error')
      expect(document.querySelector('#sync-status .sync-dot').className).toBe('sync-dot red')
    })

    it('does not throw when badge DOM is absent', () => {
      document.body.innerHTML = ''
      const badge = initSyncBadge()
      expect(() => badge.setSyncStatus('green', 'saved')).not.toThrow()
    })
  })

  describe('syncLog', () => {
    it('prepends a row and mirrors to the matching console method', () => {
      const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      badge.syncLog('info', 'SAVE', 'wrote file')
      const body = document.getElementById('sync-debug-body')
      expect(body.children.length).toBe(1)
      const row = body.firstChild
      expect(row.className).toBe('sdp-row')
      expect(row.querySelector('.sdp-type').textContent).toBe('SAVE')
      expect(row.querySelector('.sdp-msg').textContent).toBe('wrote file')
      expect(spy).toHaveBeenCalledWith('[SYNC][SAVE] wrote file')
    })

    it('newest row is inserted first (prepended)', () => {
      vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      badge.syncLog('info', 'A', 'first')
      badge.syncLog('info', 'B', 'second')
      const body = document.getElementById('sync-debug-body')
      expect(body.firstChild.querySelector('.sdp-msg').textContent).toBe('second')
    })

    it('maps err → console.error + err type class, warn → console.warn + warn class', () => {
      const errSpy  = vi.spyOn(console, 'error').mockImplementation(() => {})
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const badge = initSyncBadge()
      badge.syncLog('err', 'X', 'boom')
      badge.syncLog('warn', 'Y', 'careful')
      const body = document.getElementById('sync-debug-body')
      // newest first: warn row at index 0, err row at index 1
      expect(body.children[0].querySelector('.sdp-type').className).toContain('warn')
      expect(body.children[1].querySelector('.sdp-type').className).toContain('err')
      expect(errSpy).toHaveBeenCalledWith('[SYNC][X] boom')
      expect(warnSpy).toHaveBeenCalledWith('[SYNC][Y] careful')
    })

    it('caps the log at 150 rows, dropping the oldest', () => {
      vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      for (let i = 0; i < 155; i++) badge.syncLog('info', 'N', `m${i}`)
      const body = document.getElementById('sync-debug-body')
      expect(body.children.length).toBe(150)
      // newest first → m154 on top, oldest surviving is m5 at the bottom
      expect(body.firstChild.querySelector('.sdp-msg').textContent).toBe('m154')
      expect(body.lastChild.querySelector('.sdp-msg').textContent).toBe('m5')
    })

    it('still console-logs when the debug body is absent', () => {
      document.getElementById('sync-debug-body').remove()
      const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      expect(() => badge.syncLog('info', 'T', 'no body')).not.toThrow()
      expect(spy).toHaveBeenCalledWith('[SYNC][T] no body')
    })
  })

  describe('debug panel visibility', () => {
    it('show / hide / toggle drive the .visible class', () => {
      const badge = initSyncBadge()
      const panel = document.getElementById('sync-debug-panel')
      expect(panel.classList.contains('visible')).toBe(false)
      badge.showDebugPanel()
      expect(panel.classList.contains('visible')).toBe(true)
      badge.hideDebugPanel()
      expect(panel.classList.contains('visible')).toBe(false)
      badge.toggleDebugPanel()
      expect(panel.classList.contains('visible')).toBe(true)
    })

    it('the close button hides the panel', () => {
      const badge = initSyncBadge()
      const panel = document.getElementById('sync-debug-panel')
      badge.showDebugPanel()
      document.getElementById('sync-debug-close').click()
      expect(panel.classList.contains('visible')).toBe(false)
    })
  })
})
