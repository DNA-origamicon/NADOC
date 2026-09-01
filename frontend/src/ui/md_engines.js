/**
 * MD Engines panel — Help-menu status check + install flow, and sidebar gates.
 *
 * `initMdEngines({ api })` → {
 *   refresh()           — re-probe GET /engines/status, update open modal + gates
 *   getStatus()         — last fetched status (or null)
 *   showStatusModal()   — the Help ▸ MD Engines panel
 *   mountSidebarGates() — install gate banners atop the oxDNA + MD sidebar bodies
 * }
 *
 * Install flow per engine (decided by md_engines_logic.actionKind):
 *   'auto'     → run the build here over /ws/engines/install with a progress modal;
 *                on failure, fall back to the copy-paste command popup.
 *   'download' → instructions popup with the (license-gated) download link + steps.
 *   'guided'   → instructions popup with the copy-paste commands.
 *
 * GPU-awareness comes straight from the backend plan (target CUDA vs CPU); this
 * module only renders it. Cohesive logic that isn't DOM lives in
 * md_engines_logic.js (unit-tested); this file is the presentational factory.
 */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import { showToast } from './toast.js'
import {
  ENGINE_ORDER, gpuSummary, actionKind, actionLabel, commandText,
  statusTone, sectionSummary, gateMessage, degradedNote,
} from './md_engines_logic.js'
import { openFilePicker } from './file_picker.js'
import { webSocketUrl } from '../shared/websocket_url.js'

// Per-engine config for the "finish a downloaded package" block: the browse `kind`
// (highlights likely files) + a placeholder. NAMD extracts a binary; ARBD builds source.
const _DOWNLOAD_ENGINES = {
  namd: { kind: 'namd', placeholder: 'path to NAMD_*.tar.gz' },
  arbd: { kind: 'arbd', placeholder: 'path to arbd*.tar.*' },
}

const _TONE = { ok: '#3fb950', warn: '#d29922', err: '#f85149' }
const _DIM = 'color:#8b949e;font-size:12px'
const _SECTION_BODY = { oxdna: 'oxdna-jobs-body', md: 'md-panel-body' }

export function initMdEngines({ api }) {
  let _status = null
  let _statusModal = null          // the Help-menu status modal (rebuildable body)
  const _gates = {}                // section → gate root element

  // ── data ────────────────────────────────────────────────────────────────
  async function refresh() {
    _status = await api.enginesStatus().catch(() => null)
    if (_statusModal && _statusModal.isOpen()) _renderStatusBody()
    _updateGates()
    return _status
  }
  const getStatus = () => _status

  // ── Help ▸ MD Engines status modal ───────────────────────────────────────
  async function showStatusModal() {
    if (_statusModal && _statusModal.isOpen()) return
    if (!_status) await refresh()
    const body = el('div')
    _statusModal = createModal({
      title: 'MD Engines',
      size: 'lg',
      body,
      actions: [
        createButton({ label: 'Re-check', onClick: () => refresh() }),
        createButton({ label: 'Close', variant: 'primary', onClick: () => _statusModal.close() }),
      ],
    })
    _statusModal._bodyEl = body
    _renderStatusBody()
    _statusModal.open()
  }

  function _renderStatusBody() {
    const body = _statusModal && _statusModal._bodyEl
    if (!body) return
    body.replaceChildren()
    if (!_status) {
      body.appendChild(el('div', { text: 'Could not read engine status — is the backend running?', attrs: { style: _DIM } }))
      return
    }
    body.appendChild(el('div', {
      text: gpuSummary(_status.gpu),
      attrs: { style: 'margin-bottom:4px;font-size:13px' },
    }))
    if (_status.wsl) {
      body.appendChild(el('div', {
        text: 'Running in WSL — engines install on the Linux side (a Windows-side download under /mnt/c/… can’t run).',
        attrs: { style: _DIM + ';margin-bottom:12px' },
      }))
    }
    for (const key of ENGINE_ORDER) {
      const eng = _status.engines[key]
      if (eng) body.appendChild(_engineRow(eng))
    }
  }

  function _engineRow(eng) {
    const dot = el('span', { attrs: { style:
      `display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;flex:0 0 auto;background:${_TONE[statusTone(eng)]}` } })
    const name = el('span', { text: eng.name, attrs: { style: 'font-weight:600' } })
    const head = el('div', { attrs: { style: 'display:flex;align-items:center' }, children: [dot, name] })

    // Degraded = installed but CPU-only while a GPU is present: show the path AND
    // a warning note, and offer the rebuild action instead of a passive "✓ installed".
    const degraded = !!eng.degraded
    const lines = [el('div', { text: eng.purpose, attrs: { style: _DIM } })]
    if (eng.installed) {
      lines.push(el('div', { text: eng.path, attrs: { style: 'color:#6e7681;font-size:11px;font-family:monospace;word-break:break-all' } }))
      const dnote = degradedNote(eng)
      if (dnote) lines.push(el('div', { text: dnote, attrs: { style: `color:${_TONE.warn};font-size:12px` } }))
    } else if (eng.required_note) {
      lines.push(el('div', { text: eng.required_note, attrs: { style: _DIM + ';font-style:italic' } }))
    }

    const right = (eng.installed && !degraded)
      ? el('span', { text: '✓ installed', attrs: { style: `color:${_TONE.ok};font-size:12px;white-space:nowrap` } })
      : createButton({ label: actionLabel(eng), size: 'sm', variant: 'primary', onClick: () => _handleAction(eng.key) })

    const left = el('div', { attrs: { style: 'flex:1 1 auto;min-width:0' }, children: [head, ...lines] })
    return el('div', {
      attrs: { style: 'display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-bottom:1px solid #21262d' },
      children: [left, el('div', { attrs: { style: 'flex:0 0 auto' }, children: [right] })],
    })
  }

  // ── install dispatch ──────────────────────────────────────────────────────
  function _handleAction(key) {
    const eng = _status && _status.engines[key]
    if (!eng) return
    const kind = actionKind(eng)
    if (kind === 'auto') _runAutoInstall(eng)
    else _showInstructions(eng)   // 'download' | 'guided'
  }

  // Shared progress modal + WS streaming for any install (source build OR finishing
  // a downloaded package). onComplete()/onError(message) decide what happens next.
  function _wsInstall({ title, payload, onComplete, onError, onManualStep }) {
    const stage = el('div', { text: 'Starting…', attrs: { style: 'font-size:13px;margin-bottom:8px' } })
    const bar = el('div', { attrs: { style: 'height:100%;width:0%;background:#1f6feb;transition:width .3s' } })
    const barWrap = el('div', { attrs: { style: 'height:8px;background:#21262d;border-radius:4px;overflow:hidden;margin-bottom:10px' }, children: [bar] })
    const log = el('pre', { attrs: { style: 'max-height:220px;overflow:auto;background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:8px;font-size:11px;color:#8b949e;margin:0;white-space:pre-wrap' } })

    let ws = null
    let done = false
    const modal = createModal({
      title, size: 'md', dismissOnBackdrop: false,
      body: [stage, barWrap, log],
      actions: [createButton({ label: 'Cancel', onClick: () => { _closeWs(); modal.close() } })],
      onClose: () => { _closeWs() },
    })
    function _closeWs() { if (ws) { ws.onmessage = ws.onerror = ws.onclose = null; try { ws.close() } catch {} ws = null } }
    function _append(line) { log.appendChild(document.createTextNode(line + '\n')); log.scrollTop = log.scrollHeight }
    function _fail(m) { done = true; _closeWs(); modal.close(); onError && onError(m) }

    modal.open()
    try {
      ws = new WebSocket(webSocketUrl('/ws/engines/install'))
    } catch (e) {
      modal.close(); onError && onError('Could not open a connection to the install service.'); return
    }
    ws.onopen = () => ws.send(JSON.stringify(payload))
    ws.onmessage = ({ data }) => {
      let msg; try { msg = JSON.parse(data) } catch { return }
      if (msg.type === 'progress') {
        // Show the live number next to the stage: a climbing % is what tells the
        // user the build is progressing and not stuck in a loop.
        stage.textContent = (msg.pct != null) ? `${msg.stage} — ${msg.pct}%` : msg.stage
        bar.style.width = `${msg.pct}%`
      }
      else if (msg.type === 'log') { _append(msg.line) }
      else if (msg.type === 'complete') { done = true; _closeWs(); modal.close(); onComplete && onComplete(msg) }
      else if (msg.type === 'manual_step') { done = true; _closeWs(); modal.close(); (onManualStep || _showManualStep)(msg) }
      else if (msg.type === 'error') { _fail(msg.message) }
    }
    ws.onerror = () => { if (!done) _fail('Could not reach the install service.') }
    ws.onclose = () => { if (!done) _fail('Connection closed before finishing.') }
  }

  // try-auto build; on failure, fall back to the manual command popup
  function _runAutoInstall(eng) {
    _wsInstall({
      title: `Installing ${eng.name} (${eng.install.target})`,
      payload: { engine: eng.key },
      onComplete: () => { showToast(`${eng.name} installed ✓`, { severity: 'ok' }); refresh() },
      onError: (m) => {
        showToast(`${eng.name} auto-install failed — showing manual steps`, { severity: 'error' })
        _showInstructions(eng, m)
      },
    })
  }

  // "Where do I paste these?" callout — renders the backend's terminal_help
  // (WSL / macOS / Linux specific) as a prominent, hard-to-miss box with a
  // one-line self-check so the user confirms they're in the right shell.
  function _terminalHelpBlock() {
    const help = _status && _status.terminal_help
    if (!help) return null
    const children = [
      el('div', { text: help.heading, attrs: { style: 'font-size:13px;font-weight:600;color:#f0b429;margin-bottom:6px' } }),
    ]
    for (const s of (help.steps || [])) {
      children.push(el('div', { text: '• ' + s, attrs: { style: 'font-size:12px;color:#c9d1d9;margin:3px 0;line-height:1.45' } }))
    }
    const chk = help.check
    if (chk && chk.cmd) {
      children.push(el('div', {
        attrs: { style: 'margin-top:8px;padding-top:8px;border-top:1px solid #3a2f0a' },
        children: [
          el('div', { text: `Not sure? Type  ${chk.cmd}  and press Enter to check:`, attrs: { style: _DIM } }),
          ...(chk.pass ? [el('div', { text: '✓ ' + chk.pass, attrs: { style: `color:${_TONE.ok};font-size:12px;margin-top:2px` } })] : []),
          ...(chk.fail ? [el('div', { text: '✗ ' + chk.fail, attrs: { style: `color:${_TONE.err};font-size:12px;margin-top:2px` } })] : []),
        ],
      }))
    }
    return el('div', {
      attrs: { style: 'border:1px solid #d29922;background:#1c1908;border-radius:6px;padding:10px;margin:6px 0 10px' },
      children,
    })
  }

  // instructions popup: download links + copy-paste commands + doc pointer
  function _showInstructions(eng, errorNote) {
    const inst = eng.install || {}
    const parts = []
    if (errorNote) parts.push(el('div', { text: errorNote, attrs: { style: `color:${_TONE.err};font-size:12px;margin-bottom:8px` } }))
    if (inst.note) parts.push(el('div', { text: inst.note, attrs: { style: 'font-size:13px;margin-bottom:10px' } }))
    // Any "what/why is being installed" explanation goes behind an expandable
    // Details section — the commands themselves (below) are the primary content.
    if (inst.details) parts.push(el('details', {
      attrs: { style: 'margin:-4px 0 10px' },
      children: [
        el('summary', { text: 'Details', attrs: { style: _DIM + ';cursor:pointer;user-select:none' } }),
        el('div', { text: inst.details, attrs: { style: 'font-size:12px;color:#c9d1d9;margin-top:6px;line-height:1.45' } }),
      ],
    }))
    if ((inst.missing_prereqs || []).length) {
      parts.push(el('div', {
        attrs: { style: `color:${_TONE.warn};font-size:12px;margin-bottom:10px` },
        text: 'Needs first: ' + inst.missing_prereqs.join(', '),
      }))
    }
    for (const dl of (inst.downloads || [])) {
      parts.push(createButton({ label: dl.label + ' ↗', variant: 'primary', onClick: () => window.open(dl.url, '_blank', 'noopener') }))
    }
    // ARBD already built on the Linux side but not on PATH (the common WSL snag):
    // offer the one-click no-password finish up top.
    if (inst.can_finish_built) parts.push(_finishBuiltBlock(eng))
    // For download-method engines (NAMD): after the user downloads, NADOC can
    // verify the file and finish the install (extract + detect).
    if (actionKind(eng) === 'download') parts.push(_downloadFinishBlock(eng))
    const cmds = commandText(eng)
    if (cmds) {
      // Where exactly to paste — the #1 install failure is the right command in the
      // wrong shell (Windows PowerShell instead of WSL, or a C:\ path). Backend-driven
      // so the wording is accurate for this machine (WSL / macOS / Linux).
      const help = _terminalHelpBlock()
      if (help) parts.push(help)
      parts.push(el('div', { text: 'Then paste these, in order:', attrs: { style: _DIM + ';margin:10px 0 4px' } }))
      parts.push(el('pre', { text: cmds, attrs: { style: 'background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:10px;font-size:12px;color:#c9d1d9;margin:0;white-space:pre-wrap;word-break:break-all' } }))
    }
    if (inst.doc) parts.push(el('div', { text: `Full guide: ${inst.doc}`, attrs: { style: _DIM + ';margin-top:8px' } }))

    const actions = []
    if (cmds) actions.push(createButton({
      label: 'Copy commands',
      onClick: () => { navigator.clipboard?.writeText(cmds); showToast('Commands copied', { severity: 'ok' }) },
    }))
    const modal = createModal({
      title: `Install ${eng.name}`,
      size: 'md',
      body: parts,
      actions: [...actions, createButton({ label: 'Close', variant: 'primary', onClick: () => modal.close() })],
    })
    modal.open()
    return modal
  }

  // "Finish a downloaded package": the user browses to the file they downloaded,
  // NADOC verifies it, then finishes — extract + detect (NAMD) or build (ARBD).
  // The folder navigator opens at Downloads (the Windows one on WSL). Works for any
  // engine in _DOWNLOAD_ENGINES (keyed by eng.key).
  function _downloadFinishBlock(eng) {
    const cfg = _DOWNLOAD_ENGINES[eng.key] || _DOWNLOAD_ENGINES.namd
    const status = el('div', { text: 'No file chosen yet. Click Browse… and pick the file you downloaded.', attrs: { style: _DIM + ';margin:4px 0' } })
    const input = el('input', { attrs: { type: 'text', placeholder: cfg.placeholder, style: 'width:100%;box-sizing:border-box;font-size:12px;font-family:monospace;padding:5px;background:#0d1117;border:1px solid #30363d;border-radius:5px;color:#c9d1d9;margin-bottom:6px' } })

    const browse = createButton({
      label: 'Browse…', size: 'sm', variant: 'primary',
      onClick: () => openFilePicker({
        api, kind: cfg.kind, title: `Choose the downloaded ${eng.name} file`,
        onPick: (path) => {
          input.value = path
          status.style.color = ''
          status.textContent = `Chosen: ${path.split('/').pop()}. Click "Check & install".`
        },
      }),
    })
    const install = createButton({ label: 'Check & install', size: 'sm', onClick: () => _installFromArchive(eng, input.value.trim(), status) })

    return el('div', {
      attrs: { style: 'border-top:1px solid #21262d;margin-top:12px;padding-top:10px' },
      children: [
        el('div', { text: 'Already downloaded it? Pick the file and NADOC will verify + finish:', attrs: { style: 'font-size:13px;font-weight:600;margin-bottom:6px' } }),
        status, input,
        el('div', { attrs: { style: 'display:flex;gap:8px' }, children: [browse, install] }),
      ],
    })
  }

  function _installFromArchive(eng, path, statusEl) {
    if (!path) { statusEl.style.color = _TONE.err; statusEl.textContent = `Enter the path to the downloaded ${eng.name} file first.`; return }
    _wsInstall({
      title: `Installing ${eng.name} from your download`,
      payload: { engine: eng.key, archive_path: path },
      onComplete: () => { showToast(`${eng.name} installed ✓`, { severity: 'ok' }); refresh() },
      onManualStep: (msg) => { statusEl.style.color = _TONE.ok; statusEl.textContent = `${eng.name} built — one step left (see the box).`; _showManualStep(msg) },
      onError: (m) => { statusEl.style.color = _TONE.err; statusEl.textContent = m },
    })
  }

  // ARBD is built (Linux binary) but not on PATH — offer the one-click, no-password
  // finish (copy onto PATH). This is the fix for "I built it but NADOC can't find it",
  // especially on WSL where sudo make install is the missed step.
  function _finishBuiltBlock(eng) {
    return el('div', {
      attrs: { style: 'border:1px solid #238636;background:#0d1a10;border-radius:6px;padding:10px;margin:8px 0' },
      children: [
        el('div', { text: '✓ ARBD is already built — it just needs installing so NADOC can find it.', attrs: { style: 'font-size:13px;font-weight:600;margin-bottom:6px' } }),
        el('div', { text: 'No terminal needed — pick one:', attrs: { style: _DIM + ';margin-bottom:8px' } }),
        el('div', { attrs: { style: 'display:flex;gap:8px;flex-wrap:wrap' }, children: [
          createButton({ label: 'Finish install (no password)', size: 'sm', variant: 'primary', onClick: () => _finishBuiltArbd(eng) }),
          createButton({ label: 'Install system-wide (uses your password)', size: 'sm', onClick: () => _promptSudoInstall(eng) }),
        ] }),
        el('div', { text: 'No password just copies it to your user folder; system-wide runs the admin install for you.', attrs: { style: _DIM + ';margin-top:6px' } }),
      ],
    })
  }

  function _finishBuiltArbd(eng) {
    _wsInstall({
      title: 'Finishing ARBD install',
      payload: { engine: 'arbd', install_built: true },
      onComplete: () => { showToast('ARBD installed ✓', { severity: 'ok' }); refresh() },
      onError: (m) => { showToast(`Couldn't finish ARBD install — ${m}`, { severity: 'error' }) },
    })
  }

  // For users who'd rather not touch a terminal: collect the computer password and
  // let the backend run `sudo make install`. The password is used once for that
  // command and is not stored (localhost-only tool).
  function _promptSudoInstall(eng) {
    const pw = el('input', { attrs: { type: 'password', placeholder: 'Your computer password', autocomplete: 'off',
      style: 'width:100%;box-sizing:border-box;font-size:13px;padding:7px;background:#0d1117;border:1px solid #30363d;border-radius:5px;color:#c9d1d9;margin-top:8px' } })
    const errLine = el('div', { attrs: { style: `color:${_TONE.err};font-size:12px;margin-top:6px;display:none` } })
    const run = () => {
      if (!pw.value) { errLine.style.display = ''; errLine.textContent = 'Enter your password first.'; return }
      const password = pw.value
      modal.close()
      _wsInstall({
        title: 'Installing ARBD (system-wide)',
        payload: { engine: 'arbd', sudo_install: true, password },
        onComplete: () => { showToast('ARBD installed ✓', { severity: 'ok' }); refresh() },
        onError: (m) => { showToast(`ARBD install failed — ${m}`, { severity: 'error' }) },
      })
    }
    pw.addEventListener('keydown', (e) => { if (e.key === 'Enter') run() })
    const modal = createModal({
      title: 'Install ARBD system-wide',
      size: 'sm',
      body: [
        el('div', { text: 'This runs the one admin step for you (sudo make install → /usr/local/bin/arbd). Your password is used only for this command and is not saved.', attrs: { style: 'font-size:13px' } }),
        pw, errLine,
      ],
      actions: [
        createButton({ label: 'Cancel', onClick: () => modal.close() }),
        createButton({ label: 'Install', variant: 'primary', onClick: run }),
      ],
    })
    modal.open()
  }

  // Some installs (ARBD) can finish with one sudo line the background service can't
  // run. Show that line big with Copy — plus the no-password finish when available.
  function _showManualStep(msg) {
    const cmd = msg.command || ''
    const note = msg.note || 'Paste this line in a terminal to finish, then click Re-check.'
    const actions = []
    if (msg.can_finish_built) {
      actions.push(createButton({
        label: 'Finish install (no password)', variant: 'primary',
        onClick: () => { modal.close(); _finishBuiltArbd({ key: 'arbd', name: 'ARBD' }) },
      }))
      actions.push(createButton({
        label: 'Run it for me (password)',
        onClick: () => { modal.close(); _promptSudoInstall({ key: 'arbd', name: 'ARBD' }) },
      }))
    }
    actions.push(createButton({ label: 'Copy command', onClick: () => { navigator.clipboard?.writeText(cmd); showToast('Command copied', { severity: 'ok' }) } }))
    actions.push(createButton({ label: 'Done', variant: msg.can_finish_built ? 'default' : 'primary', onClick: () => { modal.close(); refresh() } }))
    const modal = createModal({
      title: 'One step left to finish',
      size: 'md',
      body: [
        el('div', { text: note, attrs: { style: 'font-size:13px;margin-bottom:10px;white-space:pre-wrap' } }),
        el('pre', { text: cmd, attrs: { style: 'background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:10px;font-size:13px;color:#c9d1d9;margin:0;white-space:pre-wrap;word-break:break-all' } }),
      ],
      actions,
    })
    modal.open()
  }

  // ── sidebar gates ─────────────────────────────────────────────────────────
  function mountSidebarGates() {
    for (const section of Object.keys(_SECTION_BODY)) {
      const host = document.getElementById(_SECTION_BODY[section])
      if (!host || _gates[section]) continue
      const gate = el('div', {
        id: `engines-gate-${section}`,
        attrs: { style: 'display:none;border:1px solid #d29922;background:#1c1908;border-radius:6px;padding:10px;margin-bottom:8px' },
      })
      host.insertBefore(gate, host.firstChild)
      _gates[section] = gate
    }
    _updateGates()
  }

  function _updateGates() {
    for (const section of Object.keys(_gates)) {
      const gate = _gates[section]
      const { ready } = sectionSummary(_status, section)
      if (!_status || ready) { gate.style.display = 'none'; continue }
      gate.style.display = ''
      gate.replaceChildren(
        el('div', { text: '⚠ ' + gateMessage(_status, section), attrs: { style: 'font-size:13px;font-weight:600;margin-bottom:4px' } }),
        el('div', { text: 'This section needs it installed to run. The controls below stay disabled until then.', attrs: { style: _DIM + ';margin-bottom:8px' } }),
        createButton({ label: 'Set up engines…', size: 'sm', variant: 'primary', onClick: () => showStatusModal() }),
      )
    }
  }

  return { refresh, getStatus, showStatusModal, mountSidebarGates }
}
