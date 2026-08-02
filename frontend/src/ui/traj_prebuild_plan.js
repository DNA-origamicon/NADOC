/**
 * How many all-atom trajectory frames THIS machine can afford to hold.
 *
 * `prebuildMemoryPlan` (ui/oxdna_display.js) is the pure half — cost per frame, which
 * ceiling binds. The impure half is one backend read (the host's MemAvailable) plus a
 * short cache so a prebuild decision doesn't poll it. That half lived inside
 * md_jobs_panel.js, which meant the animation player had no way to price a prebuild
 * without copying it a third time.
 *
 * A FACTORY, not module-level state: the RAM reading is cached, and one shared cache
 * would leak a stale reading between consumers (and, more sharply, between test cases).
 * Each consumer makes one instance, so its own callers price against one budget — which
 * is what md_jobs_panel's two callers (DNA prebuild + solvent) already relied on.
 */

import { prebuildMemoryPlan } from './oxdna_display.js'

/** How long a MemAvailable reading stays good. It is a rough "roughly how much can we
 *  spare", not a measurement — re-reading it per frame would be noise, not precision. */
export const RAM_CACHE_MS = 10_000

export function initTrajPrebuildPlan({ api, cacheMs = RAM_CACHE_MS, now = () => Date.now() } = {}) {
  let _cache = null

  /** Host MemAvailable in bytes, or null when unknown. The backend runs on the same
   *  machine as the browser (localhost), so its reading is the right one; if it ever
   *  isn't, null is the honest answer and the fixed budget still applies. */
  async function freeRamBytes() {
    const t = now()
    if (_cache && t - _cache.at < cacheMs) return _cache.bytes
    const r = await Promise.resolve(api?.getSystemResources?.()).catch(() => null)
    const mb = Number(r?.ram_available_mb)
    const bytes = Number.isFinite(mb) && mb > 0 ? mb * 1024 * 1024 : null
    _cache = { at: t, bytes }
    return bytes
  }

  /** Synchronous read of the cached reading (null until freeRamBytes() has run once).
   *  For consumers that must answer now and can treat "unknown" as "no RAM limit". */
  function lastFreeRamBytes() { return _cache?.bytes ?? null }

  /** What an all-atom prebuild of `controller`'s loaded trajectory would cost here.
   *  Null when the controller holds no trajectory (nothing to price). */
  async function planFor(controller) {
    const info = controller?.trajectoryInfo?.() || {}
    const nFrames = Number(info.total) || 0
    if (!nFrames) return null
    return prebuildMemoryPlan({
      nFrames,
      nSerials:      Number(info.atomSerials)   || 0,
      nNucleotides:  Number(info.nNucleotides)  || 0,
      availableBytes: await freeRamBytes(),
    })
  }

  return { freeRamBytes, lastFreeRamBytes, planFor }
}
