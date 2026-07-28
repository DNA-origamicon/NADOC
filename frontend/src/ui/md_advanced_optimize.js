/**
 * Advanced-card ⚡ Optimize — propose NAMD settings that suit THIS design on THIS machine.
 *
 * The backend (backend/core/md_optimize.py) owns the policy; this module owns the UX
 * contract around it: never touch the user's inputs without showing exactly what will
 * change and what the caveats are, then require an explicit Proceed.
 *
 * The caveats are not boilerplate.  The recommendation can flip the run onto a
 * different NAMD code path (a water-shell carve disables GPU-resident mode and forces
 * NVT), and its throughput numbers are extrapolated from two benchmarks — so the popup
 * has to say so before the user commits a multi-hour run to it.
 */

/** Field order + labels for the diff table.  Keys match the backend's `recommended`. */
const FIELDS = [
  { key: 'threads',        label: 'Threads' },
  { key: 'compute',        label: 'Compute' },
  { key: 'water_shell_a',  label: 'Water shell', unit: ' Å' },
  { key: 'padding_nm',     label: 'Padding',     unit: ' nm' },
  { key: 'minimize_steps', label: 'Min. steps' },
  { key: 'fast',           label: 'Fast (HMR 4 fs)' },
  // The backend has always computed this (it is what the carve trade-off turns on) but
  // the card never showed or applied it, so ⚡ silently left the user's GPU-resident
  // choice untouched while claiming to have optimised the run path.
  { key: 'gpu_resident',   label: 'GPU-resident' },
]

/** The recommender speaks booleans for gpu_resident; the control is an auto/on/off
 *  select. Optimize expresses an OPINION, so it maps to the explicit on/off — never
 *  back to 'auto', which would mean "no opinion" and discard the recommendation. */
export const residentModeFromRecommendation = (v) =>
  (v === null || v === undefined) ? null : (v ? 'on' : 'off')

const _fmt = (v, unit = '') => {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'on' : 'off'
  return `${v}${unit}`
}

/**
 * Diff the recommendation against what's currently in the form.
 * PURE. Returns one row per settable field; `changed` drives the highlight.
 * A recommended value of null/undefined means "no opinion — leave it alone".
 */
export function buildPlan(recommended = {}, current = {}) {
  const rows = []
  for (const { key, label, unit = '' } of FIELDS) {
    const to = recommended[key]
    if (to === null || to === undefined) continue          // no opinion → not in the plan
    const from = current[key]
    rows.push({
      key,
      label,
      from: _fmt(from, unit),
      to: _fmt(to, unit),
      value: to,
      changed: String(from) !== String(to),
    })
  }
  return rows
}

/** True when the proposal would actually alter something. PURE. */
export const planHasChanges = (plan = []) => plan.some(r => r.changed)

/**
 * The caveats every optimize run carries, plus any the backend added for this design.
 * PURE. These are the "limits of what might or might not work" gate.
 */
export function buildCaveats(result = {}) {
  const out = [...(result.warnings ?? [])]
  out.push(
    'Throughput figures are ESTIMATES, extrapolated from two benchmarks on this machine ' +
    'and scaled by atom count. Real runs vary — treat them as a ranking, not a promise.',
  )
  out.push(
    'This only changes run settings (threads, solvation box, integrator path). It does NOT ' +
    'change the force field, the salt, or the protocol\'s stages — the science is untouched.',
  )
  out.push(
    'Recommendations are sized for THIS machine\'s GPU and RAM. Moving the job to another ' +
    'computer may make them wrong.',
  )
  return out
}

/**
 * Which NAMD code path the current Advanced settings actually select.  PURE.
 *
 * This exists because the most consequential thing about the Advanced card is INVISIBLE:
 * a water-shell carve silently disables GPU-resident mode (NAMD aborts at step 0 on a
 * cell containing vacuum), and `fast` off does too.  Surfacing it stops the user from
 * believing they are on the fast integrator when they are not.
 *
 * @returns {{gpuResident:boolean, label:string, detail:string, tone:'ok'|'warn'|'muted'}}
 */
export function describeRunPath({ compute = 'gpu', water_shell_a = 0, fast = true } = {}) {
  const shell = Number(water_shell_a) || 0
  if (compute === 'cpu') {
    return {
      gpuResident: false, tone: 'muted', label: 'CPU (multicore)',
      detail: 'No GPU. Required for implicit solvent; far slower for explicit water.',
    }
  }
  if (shell > 0) {
    return {
      gpuResident: false, tone: 'warn', label: 'CUDA offload',
      detail: `GPU-resident is OFF — the ${shell} Å water shell leaves vacuum in the cell, ` +
              'which GPU-resident cannot handle. Nonbonded + PME still run on the GPU. NVT (no barostat).',
    }
  }
  if (!fast) {
    return {
      gpuResident: false, tone: 'muted', label: 'CUDA offload',
      detail: 'GPU-resident is OFF because Fast (HMR 4 fs) is unchecked.',
    }
  }
  return {
    gpuResident: true, tone: 'ok', label: 'GPU-resident',
    detail: 'Full box, no carve — integrator + bonded forces stay on the GPU (~2.6x faster per atom).',
  }
}

/**
 * Warn when the chosen PRODUCTION timestep is riskier than what THIS job's relaxation
 * validated.  PURE.  The "fast relaxation ladder" (the Fast checkbox) is what builds and
 * validates the HMR structure that makes 4 fs rigid dynamics stable; without it, an
 * elevated timestep is a gamble.
 *
 * @param {{timestepFs:number, fastLadder:boolean}} opts
 * @returns {{tone:'warn'|'error', message:string} | null}  null = no warning needed.
 */
export function productionTimestepWarning({ timestepFs = 4, fastLadder = true } = {}) {
  const ts = Number(timestepFs)
  if (fastLadder) return null                     // ladder validated 4 fs → any dt is safe
  if (ts >= 4) {
    return {
      tone: 'error',
      message: '4 fs production needs the fast relaxation ladder (it builds & validates the '
             + 'HMR structure). With Fast relaxation off there is no repartitioned PSF — the '
             + 'run is likely to blow up in RATTLE. Enable Fast relaxation, or drop to 2 / 1 fs.',
    }
  }
  if (ts === 2) {
    return {
      tone: 'warn',
      message: '2 fs without the fast relaxation ladder: it runs rigidBonds-all on standard '
             + 'masses (usually stable), but this design was not ladder-validated at 2 fs — '
             + 'watch the first frames for RATTLE / fast-atom warnings.',
    }
  }
  return null                                     // 1 fs conservative reference → always safe
}

/** Atom count below which GPU-resident is a measured LOSS (mirrors the backend's
 *  md_protocols._RESIDENT_MIN_ATOMS, which gates the emitted confs). */
export const RESIDENT_MIN_ATOMS = 100_000

/**
 * Warn when a FORCED GPU-resident choice disagrees with what the system size supports.
 * PURE.  `null` = nothing to say.
 *
 * Resident is not a "faster" switch — its advantage scales with N.  Measured on an
 * RTX 3080 Ti (offload → resident ms/step): 32.5k 1.116→1.266 (0.88x, a LOSS), 111k
 * 1.749→1.544, 181k 3.338→2.507, 770k 32.10→16.16, 3.14M 125.6→39.0 (3.2x).  Forcing it
 * on a small design costs throughput; forcing it off on a large one costs much more.
 *
 * @param {{mode:'auto'|'on'|'off', nAtoms:number|null}} opts
 */
export function gpuResidentWarning({ mode = 'auto', nAtoms = null } = {}) {
  if (mode === 'auto' || nAtoms == null || !(nAtoms > 0)) return null
  const n = Math.round(nAtoms)
  const pretty = n.toLocaleString('en-US')
  if (mode === 'on' && n < RESIDENT_MIN_ATOMS) {
    return {
      tone: 'warn',
      message: `Forcing GPU-resident on ~${pretty} atoms will be SLOWER than CUDA offload `
             + `(measured 0.88–0.97× below ~${RESIDENT_MIN_ATOMS.toLocaleString('en-US')} `
             + `atoms — both paths hit the same per-step floor and resident's setup is pure `
             + `overhead). Auto would pick offload here.`,
    }
  }
  if (mode === 'off' && n >= RESIDENT_MIN_ATOMS) {
    return {
      tone: 'warn',
      message: `Forcing CUDA offload on ~${pretty} atoms gives up a real speed-up — `
             + `GPU-resident measured 1.1× at 111k, 2.0× at 770k and 3.2× at 3.14M atoms. `
             + `Auto would pick resident here.`,
    }
  }
  return null
}

/** Escape text before it goes into innerHTML. */
const esc = (s) => String(s).replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
))

// ── Progress ─────────────────────────────────────────────────────────────────
// The stage boundaries below are REAL — each is a separate awaited backend call, not
// a timed animation.  `sizing` is the slow one (~26 s on a 6-helix bundle: it builds
// the design's full heavy-atom model and grid-measures its hydration volume), which
// is exactly why it is worth showing at all.
export const OPTIMIZE_STAGES = [
  { key: 'hardware', label: 'Reading GPU, RAM and CPU' },
  { key: 'sizing',   label: 'Building heavy-atom model, measuring hydration volume' },
  { key: 'choose',   label: 'Scoring candidate water shells and settings' },
]

/** Percent complete once *done* of *total* stages have finished. PURE. */
export function stagePercent(done, total = OPTIMIZE_STAGES.length) {
  if (!total || total < 0) return 0
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)))
}

/** "Step 2/3 · Building… · 12s". PURE — the status line under the card title. */
export function formatStageLine(index, elapsedS, stages = OPTIMIZE_STAGES) {
  const s = stages[index]
  if (!s) return ''
  const t = elapsedS > 0 ? ` · ${elapsedS}s` : ''
  return `Step ${index + 1}/${stages.length} · ${s.label}${t}`
}

/**
 * Progress bar + status line, rendered into *el* (which lives directly under the
 * Advanced card title so it stays visible even when the drawer is collapsed).
 */
export function createOptimizeProgress(el) {
  let timer = null
  let t0 = 0

  const paint = (pct, text, tone = '#58a6ff') => {
    if (!el) return
    el.style.display = 'block'
    el.innerHTML =
      `<div style="height:3px;background:#21262d;border-radius:2px;overflow:hidden">
         <div style="height:100%;width:${pct}%;background:${tone};transition:width .25s"></div>
       </div>
       <div style="margin-top:3px;color:#8b949e;font-size:var(--text-xs)">${esc(text)}</div>`
  }

  const stop = () => { if (timer) { clearInterval(timer); timer = null } }

  return {
    /** Enter stage *index*; ticks an elapsed-seconds counter (real, not simulated). */
    stage(index) {
      stop()
      t0 = Date.now()
      const tick = () => paint(
        stagePercent(index), formatStageLine(index, Math.round((Date.now() - t0) / 1000)))
      tick()
      timer = setInterval(tick, 1000)
    },
    done(text = 'Done.') { stop(); paint(100, text, '#3fb950') },
    fail(text) { stop(); paint(100, text, '#f85149') },
    hide() { stop(); if (el) { el.style.display = 'none'; el.innerHTML = '' } },
  }
}

// ── Pre-flight ───────────────────────────────────────────────────────────────
/**
 * What ⚡ Optimize is about to do — shown BEFORE any work starts.  PURE.
 *
 * Deliberately does NOT say "runs tests" or "benchmarks your GPU": it runs neither.
 * It reads the hardware, builds a heavy-atom model of the design to size its water
 * box, and scores that against benchmarks recorded earlier.  Saying otherwise would
 * be a lie the user would reasonably act on.
 */
export function buildPreflight({ designName = 'this design' } = {}) {
  return {
    title: 'Optimize will take a moment',
    lead: `About to work out the best NAMD settings for ${designName} on this machine.`,
    steps: OPTIMIZE_STAGES.map(s => s.label),
    notes: [
      'This does NOT run a simulation or benchmark your GPU. Nothing is submitted, and no ' +
      'job is created — it only reads your hardware and measures the design.',
      'Building the heavy-atom model is the slow step: typically ~30 seconds, but it scales ' +
      'with design size and can take several minutes on a very large origami.',
      'Nothing is changed until you approve the proposal on the next screen.',
    ],
  }
}

/** The pre-flight popup. Resolves true to continue, false to cancel. */
function showPreflightModal(pf) {
  return new Promise((resolve) => {
    const back = document.createElement('div')
    back.id = 'md-optimize-preflight'
    back.style.cssText =
      'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:10000;' +
      'display:flex;align-items:center;justify-content:center'
    back.innerHTML = `
      <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;max-width:520px;
                  width:calc(100% - 40px);padding:16px;font-size:var(--text-xs,12px);color:#c9d1d9">
        <div style="font-size:14px;font-weight:600;margin-bottom:2px">⚡ ${esc(pf.title)}</div>
        <div style="color:#8b949e;margin-bottom:10px">${esc(pf.lead)}</div>
        <div style="font-weight:600;color:#8b949e">It will:</div>
        <ol style="margin:4px 0 0;padding-left:20px;color:#8b949e;line-height:1.55">
          ${pf.steps.map(s => `<li>${esc(s)}</li>`).join('')}
        </ol>
        <ul style="margin:10px 0 0;padding-left:18px;color:#8b949e;line-height:1.55">
          ${pf.notes.map(n => `<li>${esc(n)}</li>`).join('')}
        </ul>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
          <button id="md-optimize-pf-cancel"
                  style="padding:5px 12px;background:#21262d;border:1px solid #30363d;color:#c9d1d9;
                         border-radius:4px;cursor:pointer">Cancel</button>
          <button id="md-optimize-pf-go"
                  style="padding:5px 12px;background:#238636;border:1px solid #2ea043;color:#fff;
                         border-radius:4px;cursor:pointer">Continue</button>
        </div>
      </div>`
    const close = (v) => { document.removeEventListener('keydown', onKey); back.remove(); resolve(v) }
    const onKey = (e) => { if (e.key === 'Escape') close(false) }
    back.querySelector('#md-optimize-pf-cancel').onclick = () => close(false)
    back.querySelector('#md-optimize-pf-go').onclick = () => close(true)
    back.onclick = (e) => { if (e.target === back) close(false) }
    document.addEventListener('keydown', onKey)
    document.body.appendChild(back)
  })
}

/** Render the confirm modal. Resolves true on Proceed, false on Cancel/Esc/backdrop. */
function showOptimizeModal({ plan, rationale, caveats, facts }) {
  return new Promise((resolve) => {
    const back = document.createElement('div')
    back.id = 'md-optimize-modal'
    back.style.cssText =
      'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:10000;' +
      'display:flex;align-items:center;justify-content:center'

    const rows = plan.map(r => `
      <tr style="${r.changed ? '' : 'opacity:.45'}">
        <td style="padding:2px 8px 2px 0;color:#8b949e">${esc(r.label)}</td>
        <td style="padding:2px 8px 2px 0;color:#6e7681">${esc(r.from)}</td>
        <td style="padding:2px 8px 2px 0;color:#6e7681">→</td>
        <td style="padding:2px 0;color:${r.changed ? '#3fb950' : '#8b949e'};font-weight:${r.changed ? '600' : '400'}">${esc(r.to)}</td>
      </tr>`).join('')

    const est = facts?.est_ns_per_day
    const estLine = est
      ? `<div style="margin:6px 0 0;color:#8b949e;font-size:11px">Estimated ≈ <b style="color:#c9d1d9">${esc(est)} ns/day</b>
         at ~${esc((facts.chosen_atoms ?? 0).toLocaleString())} atoms
         (${facts.gpu_resident ? 'GPU-resident' : 'CUDA offload'}).</div>`
      : ''

    back.innerHTML = `
      <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;max-width:600px;
                  width:calc(100% - 40px);max-height:80vh;overflow:auto;padding:16px;
                  font-size:var(--text-xs,12px);color:#c9d1d9">
        <div style="font-size:14px;font-weight:600;margin-bottom:2px">⚡ Optimize Advanced settings</div>
        <div style="color:#8b949e;margin-bottom:12px">Proposed for this design on this machine.</div>

        ${plan.length
          ? `<table style="border-collapse:collapse;margin-bottom:10px">${rows}</table>${estLine}`
          : '<div style="color:#8b949e;margin-bottom:10px">Your current settings already look optimal — nothing to change.</div>'}

        ${rationale?.length ? `
          <div style="margin-top:12px;font-weight:600;color:#8b949e">Why</div>
          <ul style="margin:4px 0 0;padding-left:18px;color:#8b949e;line-height:1.5">
            ${rationale.map(r => `<li>${esc(r)}</li>`).join('')}
          </ul>` : ''}

        <div style="margin-top:14px;padding:8px;border:1px solid #9e6a03;background:#2d2000;border-radius:4px">
          <div style="font-weight:600;color:#d29922;margin-bottom:4px">⚠ Read before proceeding</div>
          <ul style="margin:0;padding-left:18px;color:#d0b184;line-height:1.5">
            ${caveats.map(c => `<li>${esc(c)}</li>`).join('')}
          </ul>
        </div>

        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
          <button id="md-optimize-cancel"
                  style="padding:5px 12px;background:#21262d;border:1px solid #30363d;color:#c9d1d9;
                         border-radius:4px;cursor:pointer">Cancel</button>
          <button id="md-optimize-proceed" ${plan.length ? '' : 'disabled'}
                  style="padding:5px 12px;background:${plan.length ? '#238636' : '#21262d'};
                         border:1px solid ${plan.length ? '#2ea043' : '#30363d'};
                         color:${plan.length ? '#fff' : '#6e7681'};border-radius:4px;
                         cursor:${plan.length ? 'pointer' : 'not-allowed'}">Proceed</button>
        </div>
      </div>`

    const close = (val) => {
      document.removeEventListener('keydown', onKey)
      back.remove()
      resolve(val)
    }
    const onKey = (e) => { if (e.key === 'Escape') close(false) }

    back.querySelector('#md-optimize-cancel').onclick = () => close(false)
    back.querySelector('#md-optimize-proceed').onclick = () => close(true)
    back.onclick = (e) => { if (e.target === back) close(false) }   // backdrop only
    document.addEventListener('keydown', onKey)
    document.body.appendChild(back)
  })
}

/**
 * Wire the ⚡ button.
 *
 * Flow: pre-flight (opt out BEFORE the ~30 s wait) → 3 real staged calls with a progress
 * bar under the card title → the proposal + caveat gate → apply only on Proceed.
 *
 * @param {object}   deps
 * @param {Element}  deps.button       the ⚡ element
 * @param {Element}  [deps.progressEl] where the bar + status line render
 * @param {Function} [deps.fetchHardware]     () => Promise<{summary,…}> — stage 1 (fast)
 * @param {Function} deps.fetchRecommendation () => Promise<{recommended,rationale,warnings,facts}> — stage 2 (slow)
 * @param {Function} deps.getCurrent  () => current form values, keyed like `recommended`
 * @param {Function} deps.apply       (recommended) => void — writes the values into the form
 * @param {Function} [deps.designName] () => string, for the pre-flight copy
 * @param {Function} [deps.notify]    (msg, kind) => void — toast
 * @param {Function} [deps.modal]     injectable for tests; defaults to the real proposal modal
 * @param {Function} [deps.preflight] injectable for tests; defaults to the real pre-flight modal
 */
export function initAdvancedOptimize({
  button, progressEl, fetchHardware, fetchRecommendation, getCurrent, apply,
  designName, notify = () => {},
  modal = showOptimizeModal, preflight = showPreflightModal,
}) {
  if (!button) return { destroy() {} }

  const progress = createOptimizeProgress(progressEl)
  let busy = false

  const onClick = async (e) => {
    // The ⚡ lives inside the Advanced drawer's click-to-toggle header — without this
    // the click would also collapse the drawer out from under the modal.
    e?.stopPropagation?.()
    // Latch SYNCHRONOUSLY, before the first await: the pre-flight is itself async, so a
    // guard set after it would let rapid clicks stack up several pre-flight popups.
    if (busy) return
    busy = true

    const label = button.textContent
    try {
      // Pre-flight FIRST, before any work: the sizing step takes ~30 s (longer on a big
      // design), so the user gets to opt out before waiting rather than after.
      const go = await preflight(buildPreflight({ designName: designName?.() }))
      if (!go) return

      button.textContent = '…'
      button.disabled = true
      // Stage 1 — hardware (fast).  A real awaited call, not a timed animation.
      progress.stage(0)
      const hw = await fetchHardware?.().catch(() => null)

      // Stage 2 — the slow one: heavy-atom model + hydration volume.
      progress.stage(1)
      const result = await fetchRecommendation()

      // Stage 3 — decide.
      progress.stage(2)
      const rec = result?.recommended ?? {}
      const plan = buildPlan(rec, getCurrent() ?? {})
      progress.done(hw?.summary ? `Ready — ${hw.summary}` : 'Ready.')

      const ok = await modal({
        plan,
        rationale: result?.rationale ?? [],
        caveats: buildCaveats(result),
        facts: result?.facts ?? {},
      })
      if (!ok) {
        progress.hide()
        notify('Optimize cancelled — nothing changed.', 'info')
        return
      }
      // Apply ONLY the fields the backend had an opinion about.
      const toApply = {}
      for (const row of plan) toApply[row.key] = row.value
      apply(toApply)
      notify(`Applied ${plan.filter(r => r.changed).length} optimized setting(s).`, 'ok')
      progress.done(`Applied ${plan.filter(r => r.changed).length} setting(s).`)
    } catch (err) {
      progress.fail(`Optimize failed: ${err?.message ?? err}`)
      notify(`Optimize failed: ${err?.message ?? err}`, 'error')
    } finally {
      button.textContent = label
      button.disabled = false
      busy = false
    }
  }

  button.addEventListener('click', onClick)
  return {
    destroy() { progress.hide(); button.removeEventListener('click', onClick) },
  }
}

const _TONE = { ok: '#3fb950', warn: '#d29922', muted: '#8b949e' }

/** Paint the derived run-path line (see describeRunPath) into *el*. */
export function renderRunPath(el, settings) {
  if (!el) return
  const p = describeRunPath(settings)
  el.title = p.detail
  el.innerHTML =
    `<span style="color:${_TONE[p.tone]}">●</span> Path: ` +
    `<b style="color:#c9d1d9">${esc(p.label)}</b>` +
    `<span style="color:#6e7681"> — ${esc(p.detail)}</span>`
}
