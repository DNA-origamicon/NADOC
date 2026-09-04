/**
 * md_metrics_card.js — the "Graphs and Metrics" card in the MD (NAMD) panel.
 *
 * A thin binding of the shared, engine-agnostic `initMetricsCard` factory (metrics_card.js)
 * to the MD REST surface (`startMdMetrics` / `getMdMetricsRun`) and the `md-metrics-*` DOM
 * ids. Twist/curvature reuse the same bundle geometry as oxDNA; base-pairing is the native
 * MD C1'…C1' fraction, aligned RMSD uses the designed duplex-core phosphates, and
 * total energy and pressure come from NAMD ENERGY records.
 * All UI behaviour lives
 * in metrics_card.js — this file only wires the endpoints + id namespace, mirroring
 * oxdna_metrics_card.js so the two engines' cards stay identical.
 */

import { startMdMetrics, getMdMetricsRun, getMdIonTransportAnalysis } from '../api/client.js'
import { initMetricsCard, METRIC_META } from './metrics_card.js'
import { openIonTransportPopup } from './ion_transport_popup.js'

export function mdJobNanoporeState(job) {
  const hasPore = !!job?.prep_params?.graphene_nanopore || job?.spawn_params?.ion_transport_mode === 'voltage'
  const analyzable = job?.run_kind === 'production' && job?.spawn_params?.ion_transport_mode === 'voltage'
  return { hasPore, analyzable }
}

export function initMdMetricsCard({ getSelectedJob = null, getJobs = null } = {}) {
  const card = initMetricsCard({
    idPrefix: 'md-metrics',
    api: {
      start: (jobId, body) => startMdMetrics(jobId, {
        ...body,
        max_frames: document.getElementById('md-metrics-all-frames')?.checked ? 0 : 64,
      }),
      poll: getMdMetricsRun,
    },
    extraMetrics: [
      { key: 'rmsd', tok: 'rmsd' },
      { key: 'energy', tok: 'energy' },
      { key: 'pressure', tok: 'pressure' },
    ],
    getSelectedJob, getJobs,
  })
  const row = document.getElementById('md-metrics-ion-transport-row')
  const button = document.getElementById('md-metrics-ion-transport-display')
  const status = document.getElementById('md-metrics-ion-transport-status')
  function syncIonTransport() {
    const state = mdJobNanoporeState(getSelectedJob?.())
    if (row) row.style.display = state.hasPore ? '' : 'none'
    if (button) button.disabled = !state.analyzable
    if (status) status.textContent = state.hasPore && !state.analyzable
      ? 'Available after spawning and running a voltage-driven production job.' : ''
  }
  button?.addEventListener('click', async () => {
    const job = getSelectedJob?.()
    if (!mdJobNanoporeState(job).analyzable) return
    button.disabled = true
    if (status) status.textContent = 'Analyzing trajectory…'
    try {
      const result = await getMdIonTransportAnalysis(job.job_id)
      if (status) status.textContent = `${Number(result.mean_current_nA || 0).toFixed(4)} nA mean · ${result.frames || 0} frames`
      openIonTransportPopup(result)
    } catch (error) {
      if (status) status.textContent = error?.message || 'Ion-transport analysis failed.'
    } finally {
      button.disabled = false
    }
  })
  const sharedRefresh = card.refresh
  card.refresh = () => { sharedRefresh(); syncIonTransport() }
  card.sync = syncIonTransport
  syncIonTransport()
  return card
}

export { METRIC_META }
