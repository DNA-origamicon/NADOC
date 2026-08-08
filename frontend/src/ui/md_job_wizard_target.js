/**
 * Job Wizard step 1 — "Where it runs".
 *
 * Compute target is now the FIRST thing the wizard asks, because it changes the
 * answers to everything after it: a local RTX, an Alpine H200 behind a queue, and a
 * rented cloud GPU differ enough in throughput and latency that the sensible run
 * length and protocol depend on which one you picked.
 *
 * Per target:
 *   local  — probes this machine's hardware and shows it, plus the run directory
 *            (a NAMD run writes multi-GB trajectories, so where they land matters).
 *   alpine — mounts the existing cluster login chip, then live availability: free
 *            GPUs, expected wait, and speed relative to THIS computer. A partition
 *            must be selected before Next.
 *   runpod — deliberately inert; wiring it is its own session.
 *
 * Pure shaping lives in `md_job_wizard_target_model.js` (separately tested); this
 * factory owns DOM, fetch, and the cluster-session subscription.
 */

import { el } from './primitives/dom.js'
import { initClusterConnection } from './cluster_connection.js'
import { getRunDir, mountDirectoryButton, runDirLabel } from './run_location.js'
import { initWizardResources } from './md_job_wizard_resources.js'
import {
  TARGETS, UNWIRED_TARGETS,
  atomCapLabel, defaultPartition, localGpuSpeedFactor, localHardwareSummary,
  partitionChoices, targetPayloadFields, targetReadiness,
} from './md_job_wizard_target_model.js'

/**
 * @param {object}   deps
 * @param {Element}  deps.mount              the wizard panel to render into
 * @param {Function} deps.fetchHardware      () => Promise<hw>  (local probe)
 * @param {Function} deps.fetchAvailability  (opts) => Promise<resp>  (Alpine)
 * @param {Function} deps.getSlurmPreview    (body) => Promise<preview> — sizes the request
 * @param {Function} deps.getTotalNs         () => number — the plan's total simulated ns
 * @param {Function} deps.onChange           called whenever target/partition changes
 * @param {string}   deps.initialTarget
 * @param {Function} [deps.readOnly]         () => boolean — showing a job that already
 *   exists. Every probe here reads the CURRENT world (this machine's GPU, who is queued on
 *   Alpine right now, what a run of this length would be sized at), none of which describes
 *   a run that has already been set up — so read-only renders the recorded answer instead
 *   of asking the world again. It also stops the step mounting the cluster login and the
 *   shared run-directory picker, neither of which belongs behind a "view settings" click.
 */
export function initWizardTargetStep({
  mount,
  fetchHardware,
  fetchAvailability,
  getSlurmPreview = undefined,
  getTotalNs = () => 0,
  fsApi = undefined,
  connect = initClusterConnection,
  onChange = () => {},
  initialTarget = 'local',
  readOnly = () => false,
} = {}) {
  let _target = initialTarget
  let _partition = null
  let _hw = null
  let _hwBusy = false
  let _avail = null
  let _availBusy = false
  let _availError = ''
  let _clusterState = 'disconnected'
  let _conn = null
  let _chipMount = null
  let _resources = null
  // What an EXISTING job recorded, in read-only mode: where it ran and the SLURM request
  // it was submitted with. Null in the ordinary live wizard.
  let _recorded = null
  const _bodies = {}

  const _ro = () => !!readOnly()

  const _localFactor = () => localGpuSpeedFactor(_hw?.gpu_name)

  function _emit() {
    onChange({ target: _target, partition: _partition, ready: readiness().ready })
  }

  // Nothing to be ready FOR in a locked view: the question was answered when the job was
  // created. The hint line stays empty because the card below already says where it ran —
  // printing it twice was just noise.
  const readiness = () => (_ro()
    ? { ready: true, reason: '' }
    : targetReadiness(_target, { clusterState: _clusterState, partition: _partition }))

  // ── local ────────────────────────────────────────────────────────────────
  async function _loadHardware() {
    // The probe reports what this machine has TODAY, which is not what the job ran on.
    if (_ro()) return
    if (_hw || _hwBusy || !fetchHardware) return
    _hwBusy = true
    _paintLocal()
    try {
      _hw = await fetchHardware()
    } catch {
      _hw = null
    } finally {
      _hwBusy = false
      _paintLocal()
    }
  }

  function _paintLocal() {
    const box = _bodies.local
    if (!box) return
    if (_ro()) {
      // No hardware summary and no run-directory picker: the first would describe today's
      // machine as though it were the one that ran, and the second is a shared app-wide
      // preference that a "view settings" click must not be able to change.
      box.innerHTML =
        '<div style="font-size:12px;color:#c9d1d9">This job was set up to run on this '
        + 'computer.</div><div style="font-size:10px;color:#6e7681;margin-top:6px;'
        + 'line-height:1.5">CPU threads and CUDA devices for the run are on the next '
        + 'step.</div>'
      return
    }
    const summary = localHardwareSummary(_hw)
    const cap = atomCapLabel(_hw)
    box.innerHTML = `
      <div style="font-size:12px;color:#c9d1d9;margin-bottom:6px">
        ${_hwBusy ? 'Detecting hardware…' : (summary || 'Could not detect this machine’s hardware.')}
      </div>
      ${cap ? `<div style="font-size:11px;color:#8b949e;margin-bottom:8px">${cap}</div>` : ''}
      <div style="font-size:11px;color:#8b949e;margin-bottom:4px">Write this run to</div>
      <div id="wiz-target-rundir"></div>
      <div style="font-size:10px;color:#6e7681;margin-top:6px;line-height:1.5">
        A NAMD run writes multi-GB trajectories. Point this at a roomy volume to keep
        them off the system disk.
      </div>
    `
    const dirMount = box.querySelector('#wiz-target-rundir')
    if (dirMount) {
      // Shared app-wide run location — the same preference the jobs list shows, so
      // changing it here changes it everywhere rather than forking a second setting.
      const btn = mountDirectoryButton(dirMount, { api: fsApi })
      if (!btn) dirMount.textContent = runDirLabel(getRunDir())
    }
  }

  // ── alpine ───────────────────────────────────────────────────────────────
  async function _loadAvailability({ force = false } = {}) {
    // Who is queued on Alpine right now says nothing about a job already set up, and the
    // preselect below would silently move a recorded partition to today's fastest node.
    if (_ro()) return
    if (_availBusy || _clusterState !== 'connected' || !fetchAvailability) return
    _availBusy = true
    _availError = ''
    _paintAlpine()
    try {
      _avail = await fetchAvailability({ force })
      // Preselect the backend's top row (it sorts by time-to-result), but never
      // overwrite a choice the user already made.
      const choices = partitionChoices(_avail, _localFactor())
      if (!_partition || !choices.some(c => c.partition === _partition && c.selectable)) {
        _partition = defaultPartition(choices)
      }
    } catch (err) {
      _avail = null
      _availError = `Could not read cluster availability: ${err?.message || err}`
    } finally {
      _availBusy = false
      _paintAlpine()
      // The preselected row is a node choice like any other, so its request gets sized
      // too — the recommended cores and wall time are on screen before the user asks.
      void _resources?.refresh()
      _emit()
    }
  }

  function _paintAlpine() {
    const box = _bodies.alpine
    if (!box) return
    if (_ro()) {
      // The recorded node, on its own. A live availability table here would show today's
      // queue beside a choice made against a queue picture that is long gone.
      box.querySelector('#wiz-target-alpine-rows').innerHTML = _partition
        ? `<div class="wiz-part-row" data-partition="${_partition}" data-selectable="0"`
          + ' style="display:grid;grid-template-columns:1.4fr .8fr .9fr 1fr;gap:10px;'
          + 'align-items:baseline;padding:7px 9px;border-radius:4px;margin-bottom:3px;'
          + 'background:rgba(31,111,235,.18);border:1px solid #1f6feb">'
          + `<span style="color:#c9d1d9;font-weight:600">${_partition}</span>`
          + '<span style="color:#6e7681;font-size:11px">—</span>'
          + '<span style="color:#6e7681;font-size:11px">—</span>'
          + '<span style="color:#6e7681;font-size:11px">chosen for this job</span></div>'
        : '<div style="font-size:11px;color:#8b949e;padding:8px 0">'
          + 'No partition was recorded for this job.</div>'
      _resources?.render()
      return
    }
    const rows = partitionChoices(_avail, _localFactor())
    const connected = _clusterState === 'connected'
    box.querySelector('#wiz-target-alpine-rows').innerHTML = !connected
      ? `<div style="font-size:11px;color:#8b949e;padding:8px 0">
           Sign in above to see which nodes are free and how long you would wait.
         </div>`
      : _availBusy
        ? '<div style="font-size:11px;color:#8b949e;padding:8px 0">Reading cluster availability…</div>'
        : _availError
          ? `<div style="font-size:11px;color:#f85149;padding:8px 0">${_availError}</div>`
          : rows.length
            ? rows.map(_rowHtml).join('')
            : '<div style="font-size:11px;color:#8b949e;padding:8px 0">No GPU partitions reported.</div>'

    box.querySelectorAll('.wiz-part-row').forEach(node => {
      if (node.dataset.selectable !== '1') return
      node.addEventListener('click', () => {
        _partition = node.dataset.partition
        _paintAlpine()
        // A different node is a different request — re-size against it straight away, so
        // the cores/wall time under the table always describe the row that is selected.
        void _resources?.refresh()
        _emit()
      })
    })
    _resources?.render()
  }

  function _rowHtml(c) {
    const sel = c.partition === _partition
    const dim = c.selectable ? '' : 'opacity:.5;'
    return (
      `<div class="wiz-part-row" data-partition="${c.partition}" ` +
      `data-selectable="${c.selectable ? '1' : '0'}" ` +
      `style="display:grid;grid-template-columns:1.4fr .8fr .9fr 1fr;gap:10px;align-items:baseline;` +
      `padding:7px 9px;border-radius:4px;margin-bottom:3px;${dim}` +
      `cursor:${c.selectable ? 'pointer' : 'default'};` +
      `background:${sel ? 'rgba(31,111,235,.18)' : 'transparent'};` +
      `border:1px solid ${sel ? '#1f6feb' : '#21262d'}">` +
      `<span><span style="color:#c9d1d9;font-weight:${sel ? 600 : 400}">${c.partition}</span>` +
      `<br><span style="color:#6e7681;font-size:9px">${c.gpuModel}</span></span>` +
      `<span style="color:#8b949e;font-size:11px" title="${c.migNote}">${c.free} free</span>` +
      `<span style="color:#c9d1d9;font-size:11px" title="${c.waitBasis}">${c.wait}</span>` +
      `<span style="color:#3fb950;font-size:11px">${c.speed || c.note}</span>` +
      `</div>`
    )
  }

  /** Mount the existing cluster login chip on first use — one auth path, not two. */
  function _ensureConnectionChip() {
    // Signing in to a cluster is not part of reading a finished job's settings.
    if (_ro()) return
    if (_conn || !_chipMount) return
    _conn = connect({ mount: _chipMount })
    _clusterState = _conn?.getState?.() || _clusterState
  }

  // ── shell ────────────────────────────────────────────────────────────────
  function _paintCards() {
    mount.querySelectorAll('.wiz-target-card').forEach(card => {
      const on = card.dataset.target === _target
      card.style.borderColor = on ? '#1f6feb' : '#30363d'
      card.style.background = on ? 'rgba(31,111,235,.12)' : '#0d1117'
      const body = _bodies[card.dataset.target]
      if (body) body.hidden = !on
    })
    const hint = mount.querySelector('#wiz-target-hint')
    if (hint) {
      const { ready, reason } = readiness()
      hint.textContent = reason
      hint.style.color = ready ? '#3fb950' : '#d29922'
    }
  }

  function _select(target) {
    if (_ro()) return
    if (_target === target) return
    _target = target
    if (target !== 'alpine') _partition = null
    _paintCards()
    if (target === 'local') _loadHardware()
    if (target === 'alpine') {
      _ensureConnectionChip()
      _loadHardware()          // still needed: the speed column is relative to local
      _loadAvailability()
    }
    _emit()
  }

  function render() {
    if (!mount) return
    mount.innerHTML = ''
    mount.appendChild(el('p', {
      text: _ro()
        ? 'Where this job was set up to run. This decided how fast it went and what it '
          + 'cost, and the rest of these settings were sized around it.'
        : 'Where should this job run? This decides how fast it goes and what it costs, '
          + 'so the rest of the wizard is sized around it.',
      attrs: { style: 'font-size:12px;color:#8b949e;margin:0 0 10px' },
    }))

    for (const t of TARGETS) {
      // A locked view shows the one target this job used — the other two cards would offer
      // a choice about a job that already exists.
      if (_ro() && t.id !== _target) continue
      const card = el('div', {
        className: 'wiz-target-card',
        dataset: { target: t.id },
        attrs: { style: 'border:1px solid #30363d;border-radius:6px;padding:10px;margin-bottom:8px;background:#0d1117' },
      })
      const head = el('div', {
        attrs: { style: 'display:flex;align-items:baseline;gap:8px;cursor:'
          + (_ro() ? 'default' : 'pointer') },
      })
      head.appendChild(el('span', {
        text: t.label,
        attrs: { style: 'font-size:13px;font-weight:600;color:#c9d1d9' },
      }))
      head.appendChild(el('span', {
        text: UNWIRED_TARGETS[t.id] ? 'not wired up yet' : t.blurb,
        attrs: { style: 'font-size:10px;color:#6e7681' },
      }))
      head.addEventListener('click', () => _select(t.id))
      card.appendChild(head)

      const body = el('div', { attrs: { style: 'margin-top:9px' } })
      body.hidden = true
      _bodies[t.id] = body

      if (t.id === 'alpine') {
        const chip = el('div', { attrs: { style: 'margin-bottom:8px' } })
        body.appendChild(chip)
        body.appendChild(el('div', {
          html: '<div style="display:grid;grid-template-columns:1.4fr .8fr .9fr 1fr;gap:10px;'
              + 'padding:2px 9px;font-size:9px;color:#6e7681;text-transform:uppercase">'
              + '<span>Partition</span><span>GPUs</span><span>Est. wait</span><span>Speed</span></div>'
              + '<div id="wiz-target-alpine-rows"></div>',
        }))
        // Cores, wall time, memory, GPUs and QoS for the selected node — sized from this
        // design. They used to be asked for by a popup after the job was already built.
        const resMount = el('div', { id: 'wiz-target-resources' })
        body.appendChild(resMount)
        _resources = initWizardResources({
          mount: resMount,
          getSlurmPreview,
          getPartition: () => _partition,
          getTotalNs,
          onChange: _emit,
          readOnly,
          // What the job actually asked for and got, so the locked block shows the run's
          // own numbers instead of re-sizing today's design.
          getRecorded: () => _recorded,
        })
        // The chip is mounted LAZILY on first Alpine selection (see _select).  Mounting
        // it here would give every user a second /api/cluster/status poller alongside
        // the Clusters card's, for a target they may never choose.
        _chipMount = chip
      } else if (t.id === 'runpod') {
        body.appendChild(el('div', {
          text: UNWIRED_TARGETS.runpod,
          attrs: { style: 'font-size:11px;color:#8b949e' },
        }))
      }
      card.appendChild(body)
      mount.appendChild(card)
    }

    mount.appendChild(el('div', {
      id: 'wiz-target-hint',
      attrs: { style: 'font-size:11px;margin-top:4px;min-height:16px' },
    }))

    _paintCards()
    _paintLocal()
    _paintAlpine()
    // Every one of these reads the live world; each no-ops in read-only.
    if (_target === 'local' || _target === 'alpine') _loadHardware()
    if (_target === 'alpine') { _ensureConnectionChip(); _loadAvailability() }
  }

  // The login chip broadcasts this; availability becomes readable the moment a
  // session exists, so refresh rather than making the user click again.
  const _onClusterState = e => {
    if (_ro()) return
    const next = e?.detail?.state || 'disconnected'
    const became = next === 'connected' && _clusterState !== 'connected'
    _clusterState = next
    if (became && _target === 'alpine') _loadAvailability()
    _paintCards()
    _paintAlpine()
    _emit()
  }
  window.addEventListener('nadoc:cluster-state-change', _onClusterState)

  /** Set the answer directly, without the live probes `_select` fires. Used to load a
   *  recorded job into the read-only view, and to put the live answer back afterwards —
   *  the step and the wizard hold this choice separately, so leaving it out of step would
   *  show one target while the payload carried another. */
  function setChoice({ target = 'local', partition = null } = {}) {
    _target = target
    _partition = partition
  }

  return {
    render,
    setChoice,
    /** Load an existing job's recorded answer for the read-only view. */
    showRecorded({ target = 'local', partition = null, resources = null, requested = null } = {}) {
      setChoice({ target, partition })
      _recorded = { resources, requested }
      _resources?.reset?.()
    },
    get target() { return _target },
    get partition() { return _partition },
    get hardware() { return _hw },
    isReady: () => readiness().ready,
    readiness,
    payloadFields: () => targetPayloadFields(_target, {
      partition: _partition,
      resources: _resources?.overrides?.() || null,
    }),
    refreshAvailability: () => _loadAvailability({ force: true }),
    /** Re-size the SLURM request — the wizard calls this when the run length changes. */
    refreshSizing: () => { if (_target === 'alpine') void _resources?.refresh() },
    dispose() {
      window.removeEventListener('nadoc:cluster-state-change', _onClusterState)
      _conn?.dispose?.()
    },
  }
}
