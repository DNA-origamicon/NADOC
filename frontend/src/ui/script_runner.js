/**
 * Script runner — interprets and executes NADOC structure scripts.
 *
 * Script JSON format
 * ------------------
 * {
 *   "name": "My Structure",
 *   "steps": [
 *     { "type": "bundle",              "cells": [[row,col],...], "length_bp": 42, "plane": "XY" },
 *     { "type": "bundle_continuation", "cells": [[row,col],...], "length_bp": 42, "plane": "XY", "count": 9 },
 *     { "type": "autostaple" }
 *   ]
 * }
 *
 * Step types
 * ----------
 *  bundle              — POST /design/bundle; creates the initial segment and replaces the active design.
 *  bundle_continuation — POST /design/bundle-continuation; extends existing strands from the current
 *                        blunt end.  "count" repeats the step N times (default 1).
 *  autostaple          — POST /design/autostaple.
 *
 * The runner automatically tracks the growing axial offset so each continuation
 * step starts exactly where the previous one ended.
 */

import { store } from '../state/store.js'
import * as api   from '../api/client.js'

// Must match backend BDNA_RISE_PER_BP constant (0.334 nm/bp).
const RISE_NM_PER_BP = 0.334

export function createScriptRunner({
  slicePlane, bluntEnds, crossoverMarkers, workspace, camera, controls,
}) {
  /**
   * Execute a parsed script object.
   * Resets the scene to a blank state first, then runs each step sequentially.
   * Throws on the first API error.
   */
  async function runScript(script) {
    // ── Reset frontend to blank state ──────────────────────────────────────
    slicePlane?.hide()
    bluntEnds?.clear()
    crossoverMarkers?.clear()
    store.setState({
      currentDesign:    null,
      currentGeometry:  null,
      validationReport: null,
      currentPlane:     null,
      strandColors:     {},
    })

    let offset = 0          // nm — current end of the last extruded segment
    let plane  = 'XY'       // active lattice plane

    for (const step of script.steps) {
      switch (step.type) {

        case 'bundle': {
          plane = step.plane ?? 'XY'
          const r = await api.createBundle({
            cells:    step.cells,
            lengthBp: step.length_bp,
            name:     script.name ?? 'Bundle',
            plane,
          })
          if (!r) throw new Error(`bundle step failed: ${store.getState().lastError?.message ?? 'unknown'}`)
          store.setState({ currentPlane: plane })
          workspace.hide()
          offset = Math.abs(step.length_bp) * RISE_NM_PER_BP
          break
        }

        case 'bundle_continuation': {
          const count = step.count ?? 1
          const p     = step.plane ?? plane
          for (let i = 0; i < count; i++) {
            const r = await api.addBundleContinuation({
              cells:    step.cells,
              lengthBp: step.length_bp,
              plane:    p,
              offsetNm: offset,
            })
            if (!r) throw new Error(
              `bundle_continuation[${i}] failed: ${store.getState().lastError?.message ?? 'unknown'}`)
            offset += Math.abs(step.length_bp) * RISE_NM_PER_BP
          }
          break
        }

        case 'autostaple': {
          const r = await api.addAutostaple()
          if (!r) throw new Error(`autostaple failed: ${store.getState().lastError?.message ?? 'unknown'}`)
          break
        }

        default:
          console.warn(`script_runner: unknown step type "${step.type}", skipping`)
      }
    }

    // ── Reposition camera to frame the finished structure ─────────────────
    const zMid = offset * 0.5
    const dist  = Math.max(20, offset * 0.6)
    camera.position.set(dist, dist * 0.4, zMid)
    controls.target.set(0, 0, zMid)
    controls.update()
  }

  return { runScript }
}
