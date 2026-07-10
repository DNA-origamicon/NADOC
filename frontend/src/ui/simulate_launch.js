/**
 * Simulate-tab launch coordinator — the "press one button, get optimal speed" glue.
 *
 * Two jobs, both driven by GET /simulate/recommendation:
 *  1. `refresh()` renders the resource + recommended-engine status line.
 *  2. `guardOxdnaLaunch()` is injected into the oxDNA panel's launch: when the GPU is
 *     busy it shows the cross-engine dialog and, if the user takes the CPU fallback,
 *     creates a LAMMPS run DIRECTLY (returning 'cpu' so oxDNA aborts). The run then
 *     appears in the unified simulate job list on the next refresh — LAMMPS is no
 *     longer a tab, so there is no engine to "switch to".
 *
 * The CPU alternative is a DIFFERENT engine (LAMMPS, multi-core), not oxDNA's
 * single-core CPU backend — that cross-engine routing is the whole point.
 */

import { simulateRecommendation } from '../api/client.js'
import { statusLineText, translateOxdnaToLammps } from './simulate_policy.js'
import { confirmSimEngineLaunch, confirmGpuLaunch } from './job_activity.js'

export function initSimulateLaunch({
  statusMount = null,
  getDevices = () => '0',
  oxdnaForm = () => ({}),
  getForces = () => ({}),
  launchLammps = async () => {},
} = {}) {
  let _last = null

  /** Fetch the recommendation and render the status line. Returns the payload (or null). */
  async function refresh() {
    const rec = await simulateRecommendation(getDevices()).catch(() => null)
    _last = rec
    if (statusMount) {
      statusMount.textContent = rec
        ? statusLineText(rec)
        : 'GPU: unknown · Engine: oxDNA (GPU) — fastest here'
    }
    return rec
  }

  /**
   * Guard for the oxDNA launch → 'gpu' | 'cpu' | 'cancel'.
   *  - GPU free/unknown → 'gpu' (oxDNA proceeds on GPU).
   *  - GPU busy + proteins → two-way GPU/cancel (LAMMPS can't do proteins).
   *  - GPU busy + no proteins → 3-way dialog; 'cpu' creates a LAMMPS run directly and
   *    returns 'cpu' so the oxDNA panel aborts its own launch.
   * Re-fetches the recommendation so the decision uses live GPU state.
   */
  async function guardOxdnaLaunch() {
    const rec = await refresh()
    const gpu = rec?.gpu
    if (!gpu || !gpu.busy) return 'gpu'

    if (rec.has_proteins) {
      // Proteins → oxDNA only, no CPU alternative: a plain "GPU busy, run anyway?".
      return confirmGpuLaunch({ usesGpu: true, hasCpuAlternative: false, devices: getDevices() })
    }

    const pick = await confirmSimEngineLaunch({
      recommendation: rec.recommendation,
      gpu,
      gpuEtaSeconds: rec.gpu_eta_seconds,
      freeCores: rec.free_cores,
    })
    if (pick === 'cpu') {
      // Create the LAMMPS run directly (no tab to switch to); it lands in the unified
      // simulate job list on refresh.
      await launchLammps(translateOxdnaToLammps({
        oxdnaForm: oxdnaForm() || {},
        forces: getForces() || {},
        freeCores: rec.free_cores || 1,
      }))
      return 'cpu'
    }
    return pick   // 'gpu' | 'cancel'
  }

  return { refresh, guardOxdnaLaunch }
}
