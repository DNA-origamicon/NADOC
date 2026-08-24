/**
 * md_metrics_card.js — the "Graphs and Metrics" card in the MD (NAMD) panel.
 *
 * A thin binding of the shared, engine-agnostic `initMetricsCard` factory (metrics_card.js)
 * to the MD REST surface (`startMdMetrics` / `getMdMetricsRun`) and the `md-metrics-*` DOM
 * ids.  Twist/curvature reuse the same bundle geometry as oxDNA; base-pairing is the native
 * MD C1'…C1' fraction (see backend md_trajectory.md_metric_series).  All UI behaviour lives
 * in metrics_card.js — this file only wires the endpoints + id namespace, mirroring
 * oxdna_metrics_card.js so the two engines' cards stay identical.
 */

import { startMdMetrics, getMdMetricsRun } from '../api/client.js'
import { initMetricsCard, METRIC_META } from './metrics_card.js'

export function initMdMetricsCard({ getSelectedJob = null, getJobs = null } = {}) {
  return initMetricsCard({
    idPrefix: 'md-metrics',
    api: {
      start: (jobId, body) => startMdMetrics(jobId, {
        ...body,
        max_frames: document.getElementById('md-metrics-all-frames')?.checked ? 0 : 64,
      }),
      poll: getMdMetricsRun,
    },
    getSelectedJob, getJobs,
  })
}

export { METRIC_META }
