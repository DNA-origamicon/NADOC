import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initSyncBadge, countCoeditingSiblings } from './sync_badge.js'

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
      badge.showDebugPanel() // console mirror is gated on the panel being open
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
      badge.showDebugPanel() // console mirror is gated on the panel being open
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

    it('still console-logs when the debug body is absent (panel open)', () => {
      document.getElementById('sync-debug-body').remove()
      const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      badge.showDebugPanel() // console mirror is gated on the panel being open
      expect(() => badge.syncLog('info', 'T', 'no body')).not.toThrow()
      expect(spy).toHaveBeenCalledWith('[SYNC][T] no body')
    })
  })

  // ISSUE-2 sub-phase C: console output is silent by default (user-approved).
  // The rolling panel log still accumulates so opening the panel shows history;
  // only the console[cls] mirror is gated behind the debug flag.
  describe('silent-by-default console (ISSUE-2 sub-phase C)', () => {
    it('does NOT mirror to console when debug logging is off (the default)', () => {
      const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      badge.syncLog('info', 'SAVE', 'wrote file')
      expect(spy).not.toHaveBeenCalled()
    })

    it('still records the row in the panel log while silent', () => {
      vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      badge.syncLog('info', 'SAVE', 'wrote file')
      const body = document.getElementById('sync-debug-body')
      expect(body.children.length).toBe(1)
      expect(body.firstChild.querySelector('.sdp-msg').textContent).toBe('wrote file')
    })

    it('mirrors to console once the debug panel is shown', () => {
      const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      badge.showDebugPanel()
      badge.syncLog('info', 'SAVE', 'wrote file')
      expect(spy).toHaveBeenCalledWith('[SYNC][SAVE] wrote file')
    })

    it('falls silent again when the debug panel is hidden', () => {
      const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      badge.showDebugPanel()
      badge.hideDebugPanel()
      badge.syncLog('info', 'SAVE', 'wrote file')
      expect(spy).not.toHaveBeenCalled()
    })

    it('the close button also silences the console mirror', () => {
      const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
      const badge = initSyncBadge()
      badge.showDebugPanel()
      document.getElementById('sync-debug-close').click()
      badge.syncLog('info', 'SAVE', 'wrote file')
      expect(spy).not.toHaveBeenCalled()
    })
  })

  // ISSUE-2 sub-phase B: the green "saved" badge must not imply siblings-in-sync.
  // When another tab holds the SAME workspace file in a different backend doc, the
  // dot turns "coedit" and the label calls it out — but only at the resting "saved"
  // (green) state; an active save / error keeps its own colour.
  describe('co-editing sibling indicator (ISSUE-2 sub-phase B)', () => {
    function dotClass() { return document.querySelector('#sync-status .sync-dot').className }
    function labelText() { return document.getElementById('sync-status-text').textContent }

    it('plain green "saved" with no siblings (the pre-fix resting state)', () => {
      const badge = initSyncBadge()
      badge.setSyncStatus('green', 'saved')
      badge.setSiblingCoediting(0)
      expect(dotClass()).toBe('sync-dot green')
      expect(labelText()).toMatch(/^saved \d{2}:\d{2}:\d{2}$/)
    })

    it('one same-file sibling → coedit dot + singular call-out (the fix)', () => {
      const badge = initSyncBadge()
      badge.setSyncStatus('green', 'saved')
      badge.setSiblingCoediting(1)
      expect(dotClass()).toBe('sync-dot coedit')
      expect(labelText()).toMatch(/^saved · 1 tab editing this file \d{2}:\d{2}:\d{2}$/)
    })

    it('two siblings → plural call-out', () => {
      const badge = initSyncBadge()
      badge.setSyncStatus('green', 'saved')
      badge.setSiblingCoediting(2)
      expect(labelText()).toMatch(/^saved · 2 tabs editing this file/)
    })

    it('an active save / error keeps its own colour (co-edit only annotates green)', () => {
      const badge = initSyncBadge()
      badge.setSiblingCoediting(1)
      badge.setSyncStatus('yellow', 'saving…')
      expect(dotClass()).toBe('sync-dot yellow')
      expect(labelText()).toMatch(/^saving… \d{2}:\d{2}:\d{2}$/)
      badge.setSyncStatus('red', 'save error')
      expect(dotClass()).toBe('sync-dot red')
    })

    it('count back to 0 reverts to plain saved', () => {
      const badge = initSyncBadge()
      badge.setSyncStatus('green', 'saved')
      badge.setSiblingCoediting(1)
      expect(dotClass()).toBe('sync-dot coedit')
      badge.setSiblingCoediting(0)
      expect(dotClass()).toBe('sync-dot green')
      expect(labelText()).toMatch(/^saved \d{2}:\d{2}:\d{2}$/)
    })

    it('the sibling annotation survives a later same-state setSyncStatus', () => {
      const badge = initSyncBadge()
      badge.setSiblingCoediting(1)
      badge.setSyncStatus('green', 'saved')   // a fresh autosave while the sibling is still open
      expect(dotClass()).toBe('sync-dot coedit')
    })

    it('does not throw when badge DOM is absent', () => {
      document.body.innerHTML = ''
      const badge = initSyncBadge()
      expect(() => badge.setSiblingCoediting(3)).not.toThrow()
    })
  })

  describe('countCoeditingSiblings (pure detector)', () => {
    it('counts an OTHER tab holding the same file in a different doc', () => {
      const others = [{ workspacePath: 'a.nadoc', docId: 'docB' }]
      expect(countCoeditingSiblings('a.nadoc', 'docA', others)).toBe(1)
    })

    it('excludes a sibling that shares our doc id (child window, genuinely in-sync)', () => {
      const others = [{ workspacePath: 'a.nadoc', docId: 'docA' }]
      expect(countCoeditingSiblings('a.nadoc', 'docA', others)).toBe(0)
    })

    it('excludes a sibling holding a different file', () => {
      const others = [{ workspacePath: 'b.nadoc', docId: 'docB' }]
      expect(countCoeditingSiblings('a.nadoc', 'docA', others)).toBe(0)
    })

    it('counts multiple distinct co-editing tabs', () => {
      const others = [
        { workspacePath: 'a.nadoc', docId: 'docB' },
        { workspacePath: 'a.nadoc', docId: 'docC' },
        { workspacePath: 'other.nadoc', docId: 'docD' },
      ]
      expect(countCoeditingSiblings('a.nadoc', 'docA', others)).toBe(2)
    })

    it('returns 0 when we have no file open (null path)', () => {
      expect(countCoeditingSiblings(null, 'docA', [{ workspacePath: 'a.nadoc', docId: 'docB' }])).toBe(0)
    })

    it('returns 0 for a non-array / empty others', () => {
      expect(countCoeditingSiblings('a.nadoc', 'docA', undefined)).toBe(0)
      expect(countCoeditingSiblings('a.nadoc', 'docA', [])).toBe(0)
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
