/**
 * joint_panel_experiments.js
 *
 * Standalone validation experiments for the lattice-based exterior-panel algorithm
 * implemented in joint_renderer.js :: _computeExteriorPanels.
 *
 * This module is pure JavaScript — no Three.js, no DOM dependencies.
 * All geometry is computed with plain math; results are printed to the console.
 *
 * ── Usage (browser DevTools console) ────────────────────────────────────────
 *
 *   // Run all four experiments:
 *   import('/src/scene/joint_panel_experiments.js').then(m => m.runAll())
 *
 *   // Run a single experiment:
 *   import('/src/scene/joint_panel_experiments.js').then(m => m.run6hbHC())
 *
 *   // Inspect raw return values:
 *   const { panels, helixUV, neighborLog } = await
 *     import('/src/scene/joint_panel_experiments.js').then(m => m.run30hbPlatformHC())
 *
 * ── Experiments ─────────────────────────────────────────────────────────────
 *
 *   run6hbHC()          — 6-helix bundle, honeycomb lattice, hexagonal ring
 *   run18hbHC()         — 18-helix elongated barrel, honeycomb lattice
 *   run30hbPlatformHC() — 30-helix wide platform, honeycomb lattice
 *   run2x6hbSQ()        — 12-helix 2×6 grid, square lattice
 *   runAll()            — all four in sequence; returns array of results
 *
 * ── Debug variables exposed in return value ─────────────────────────────────
 *
 *   panels      {angle, nu, nv, rOffset, tMin, tMax, width, contributors[]}[]
 *   helixUV     {hid, u, v, wx, wz}[]    helix positions in centroid-relative UV
 *   centX/centZ {number}                 centroid world X/Z
 *   neighborLog {source, angle, candU, candV, occupied, occupiedBy}[]
 *   pass        {boolean}                panel count matches expected
 *
 * ── Keeping in sync with production code ────────────────────────────────────
 *
 *   The algorithm constants (HC_DELTAS, SQ_DELTAS, NEIGHBOR_TOL) and the
 *   neighbour-check logic must match joint_renderer.js :: _computeExteriorPanels.
 *   If either file changes, update the other.
 */

// ── Lattice constants — mirror of backend/core/constants.py ──────────────────
//   HONEYCOMB_LATTICE_RADIUS = 1.125 nm
//   HONEYCOMB_COL_PITCH      = 1.125 * sqrt(3) ≈ 1.9486 nm
//   HONEYCOMB_ROW_PITCH      = 2.25 nm
//   SQUARE_HELIX_SPACING     = 2.25 nm

const HC_RADIUS    = 1.125
const HC_COL_PITCH = HC_RADIUS * Math.sqrt(3)   // ≈ 1.9486
const HC_ROW_PITCH = HC_RADIUS * 2              // 2.25
const SQ_PITCH     = 2.25
const NEIGHBOR_TOL = 0.5   // nm — position match tolerance

// ── Canonical Δ vectors (world XZ, CCW from +X) ───────────────────────────────
// Must match joint_renderer.js HC_DELTAS / SQ_DELTAS.

const HC_DELTAS = [
  [ HC_COL_PITCH,  HC_RADIUS    ],  //  ~30°
  [ 0,             HC_ROW_PITCH ],  //   90°
  [-HC_COL_PITCH,  HC_RADIUS    ],  //  ~150°
  [-HC_COL_PITCH, -HC_RADIUS    ],  //  ~210°
  [ 0,            -HC_ROW_PITCH ],  //  270°
  [ HC_COL_PITCH, -HC_RADIUS    ],  //  ~330°
]
const SQ_DELTAS = [
  [ SQ_PITCH, 0         ],  //   0°
  [ 0,        SQ_PITCH  ],  //  90°
  [-SQ_PITCH, 0         ],  // 180°
  [ 0,       -SQ_PITCH  ],  // 270°
]

// ── Lattice position / validity helpers ──────────────────────────────────────

/** HC cell validity.  cell_value = (row + col%2) % 3; valid when ≠ 2. */
function hcValid(row, col) {
  return (row + (col % 2)) % 3 !== 2
}

/** World XZ centre of a honeycomb cell [nm]. */
function hcPos(row, col) {
  const x = col * HC_COL_PITCH
  const z = col % 2 === 0 ? row * HC_ROW_PITCH + HC_RADIUS : row * HC_ROW_PITCH
  return [x, z]
}

/** World XZ centre of a square-lattice cell [nm]. */
function sqPos(row, col) {
  return [col * SQ_PITCH, row * SQ_PITCH]
}

/**
 * All valid HC cells in the rectangular grid
 * [rowMin..rowMax] × [colMin..colMax] (inclusive).
 */
function hcGrid(rowMin, rowMax, colMin, colMax) {
  const cells = []
  for (let r = rowMin; r <= rowMax; r++)
    for (let c = colMin; c <= colMax; c++)
      if (hcValid(r, c)) cells.push([r, c])
  return cells
}

/**
 * All SQ cells in the rectangular grid (all cells are valid).
 */
function sqGrid(rowMin, rowMax, colMin, colMax) {
  const cells = []
  for (let r = rowMin; r <= rowMax; r++)
    for (let c = colMin; c <= colMax; c++)
      cells.push([r, c])
  return cells
}

/**
 * Build a mock helixAxes object from an array of [x, z] world positions.
 * Helices are vertical (along Y) from yStart to yEnd.
 */
function makeAxes(positions, yStart = 0, yEnd = 7) {
  const axes = {}
  positions.forEach(([x, z], i) => {
    axes[`h${i}`] = { start: [x, yStart, z], end: [x, yEnd, z] }
  })
  return axes
}

// ── Core algorithm with debug logging ────────────────────────────────────────
//
// This mirrors _computeExteriorPanels in joint_renderer.js but adds:
//  - full neighbour-check logging (neighborLog)
//  - intermediate variable capture for inspection
//  - console.group output with tables

/**
 * Run the exterior-panel algorithm on a cluster and print detailed debug info.
 *
 * @param {string}   label        experiment name (shown in console)
 * @param {string[]} helixIds     array of helix IDs, e.g. ['h0','h1',…]
 * @param {object}   helixAxes    { [hid]: { start:[x,y,z], end:[x,y,z] } }
 * @param {string}   latticeType  'HONEYCOMB' | 'SQUARE'
 * @param {object}   [opts]
 * @param {number}   [opts.crossMargin=1.0]   nm added around each panel edge
 * @param {number}   [opts.expectedPanels]    override expected panel count for assertion
 *
 * @returns {{ panels, helixUV, centX, centZ, neighborLog, pass }}
 */
function runExperiment(label, helixIds, helixAxes, latticeType, opts = {}) {
  const { crossMargin = 1.0 } = opts
  const isHC            = latticeType?.toUpperCase() !== 'SQUARE'
  const deltas          = isHC ? HC_DELTAS : SQ_DELTAS
  const pitch           = isHC ? HC_ROW_PITCH : SQ_PITCH
  const expectedPanels  = opts.expectedPanels ?? (isHC ? 6 : 4)

  // ── Step 1: centroid ───────────────────────────────────────────────────────
  let sumX = 0, sumZ = 0
  for (const hid of helixIds) {
    const ax = helixAxes[hid]
    sumX += (ax.start[0] + ax.end[0]) / 2
    sumZ += (ax.start[2] + ax.end[2]) / 2
  }
  const centX = sumX / helixIds.length
  const centZ = sumZ / helixIds.length

  // ── Step 2: helix UV positions (centroid-relative) ─────────────────────────
  // For vertical bundles: U = (1,0,0) → u = world X; V = (0,0,1) → v = world Z.
  const helixUV = helixIds.map(hid => {
    const ax = helixAxes[hid]
    const u  = (ax.start[0] + ax.end[0]) / 2 - centX
    const v  = (ax.start[2] + ax.end[2]) / 2 - centZ
    return { hid, u, v, wx: ax.start[0], wz: ax.start[2] }
  })

  // ── Step 3: project Δ vectors into UV ─────────────────────────────────────
  // For vertical bundles, U.x=1 U.z=0, V.x=0 V.z=1, so du=Δx, dv=Δz.
  // Recorded here explicitly to show the projection step.
  const projDeltas = deltas.map(([dx, dz]) => ({
    du: dx,   // dx * U.x + dz * U.z
    dv: dz,   // dx * V.x + dz * V.z
    angleDeg: Math.round(Math.atan2(dz, dx) * 180 / Math.PI),
  }))

  // ── Step 4: neighbour check ────────────────────────────────────────────────
  const tol2       = NEIGHBOR_TOL ** 2
  const bins       = deltas.map(() => /** @type {{hid:string,u:number,v:number}[]} */([]))
  const neighborLog = []

  for (const { hid, u, v } of helixUV) {
    for (let di = 0; di < deltas.length; di++) {
      const { du, dv, angleDeg } = projDeltas[di]
      const cu = u + du, cv = v + dv
      let occupiedBy = null
      for (const { hid: ohid, u: ou, v: ov } of helixUV) {
        if ((ou - cu) ** 2 + (ov - cv) ** 2 < tol2) { occupiedBy = ohid; break }
      }
      neighborLog.push({
        source:      hid,
        direction:   `${angleDeg}°`,
        cand_u:      +cu.toFixed(3),
        cand_v:      +cv.toFixed(3),
        occupied:    occupiedBy !== null,
        occupied_by: occupiedBy ?? '—',
      })
      if (!occupiedBy) bins[di].push({ hid, u, v })
    }
  }

  // ── Step 5: build panels ───────────────────────────────────────────────────
  const rawPanels = []
  for (let di = 0; di < deltas.length; di++) {
    const contributors = bins[di]
    if (!contributors.length) continue
    const { du, dv } = projDeltas[di]
    const dLen = Math.sqrt(du ** 2 + dv ** 2)
    if (dLen < 1e-6) continue

    const nu = du / dLen, nv = dv / dLen   // outward unit normal
    const pu = -nv,       pv =  nu         // perpendicular (CCW)

    let rMax = -Infinity, tMin = Infinity, tMax = -Infinity
    for (const { u, v } of contributors) {
      const r = u * nu + v * nv
      const t = u * pu + v * pv
      if (r > rMax) rMax = r
      if (t < tMin) tMin = t
      if (t > tMax) tMax = t
    }

    rawPanels.push({
      angle_deg:    Math.round(Math.atan2(nv, nu) * 180 / Math.PI),
      nu:           +nu.toFixed(4),
      nv:           +nv.toFixed(4),
      rOffset_nm:   +(rMax + pitch * 0.5).toFixed(3),
      tMin_nm:      +(tMin - crossMargin).toFixed(3),
      tMax_nm:      +(tMax + crossMargin).toFixed(3),
      width_nm:     +(tMax - tMin + 2 * crossMargin).toFixed(3),
      n_contrib:    contributors.length,
      contributors: contributors.map(c => c.hid),
    })
  }
  rawPanels.sort((a, b) => a.angle_deg - b.angle_deg)

  // ── Console output ─────────────────────────────────────────────────────────
  const pass    = rawPanels.length === expectedPanels
  const badge   = pass ? '✅' : '⚠️'
  const colour  = pass ? '#44cc88' : '#ffaa44'
  const summary = `${rawPanels.length} panels — expected ${expectedPanels}`

  console.group(
    `%c${badge} ${label}   [${latticeType}, ${helixIds.length} helices, ${summary}]`,
    `font-weight:bold; color:${colour}`,
  )

  // ① Inputs
  console.group('① Helix UV positions (centroid-relative, U=world-X V=world-Z)')
  console.log(`   Centroid: x=${centX.toFixed(3)} nm,  z=${centZ.toFixed(3)} nm`)
  console.table(
    helixUV.map(h => ({
      id:     h.hid,
      u_nm:   +h.u.toFixed(3),
      v_nm:   +h.v.toFixed(3),
      wx_nm:  +h.wx.toFixed(3),
      wz_nm:  +h.wz.toFixed(3),
    })),
  )
  console.groupEnd()

  // ② Δ vectors
  console.group('② Projected Δ vectors (world XZ → local UV; trivial for vertical bundles)')
  console.table(
    projDeltas.map((pd, di) => ({
      delta_index: di,
      dx_nm:   +deltas[di][0].toFixed(4),
      dz_nm:   +deltas[di][1].toFixed(4),
      du_nm:   +pd.du.toFixed(4),
      dv_nm:   +pd.dv.toFixed(4),
      angle:   `${pd.angleDeg}°`,
    })),
  )
  console.groupEnd()

  // ③ Neighbour check matrix
  console.group('③ Neighbour-check matrix  (one row per helix × direction)')
  console.table(neighborLog)
  const extCount = neighborLog.filter(r => !r.occupied).length
  console.log(`   ${extCount} exterior faces out of ${neighborLog.length} checks`)
  console.groupEnd()

  // ④ Panels
  console.group(`④ Panels produced (${rawPanels.length}/${expectedPanels} expected)`)
  console.table(rawPanels.map(p => ({
    angle:       `${p.angle_deg}°`,
    nu:          p.nu,
    nv:          p.nv,
    rOffset_nm:  p.rOffset_nm,
    tMin_nm:     p.tMin_nm,
    tMax_nm:     p.tMax_nm,
    width_nm:    p.width_nm,
    n_contrib:   p.n_contrib,
    helices:     p.contributors.join(' '),
  })))
  console.groupEnd()

  // ⑤ ASCII width chart
  if (rawPanels.length) {
    const maxW   = Math.max(...rawPanels.map(p => p.width_nm))
    const BAR_W  = 30
    console.group('⑤ Panel width overview (bar = proportional to cross-section span)')
    const lines = rawPanels.map(p => {
      const bars = Math.round((p.width_nm / maxW) * BAR_W)
      return `${String(p.angle_deg + '°').padStart(5)}  ${'█'.repeat(bars).padEnd(BAR_W)}  ${p.width_nm.toFixed(2)} nm  (${p.n_contrib} helices)`
    })
    console.log(lines.join('\n'))
    console.groupEnd()
  }

  if (!pass) console.warn(`Expected ${expectedPanels} panels but got ${rawPanels.length}`)

  console.groupEnd()
  return { panels: rawPanels, helixUV, centX, centZ, neighborLog, pass }
}

// ── Experiment definitions ─────────────────────────────────────────────────────

/**
 * Exp 1 — 6hb HC ring
 *
 * 6 helices in a 3-column, 2-row honeycomb arrangement forming a hexagonal
 * ring cross-section.  Cells: (0,0),(1,0), (0,1),(2,1), (0,2),(1,2).
 * (Row 1 of column 1 is a hole in HC lattice, so row 2 is used instead.)
 *
 * Cross-section schematic (• = helix, _ = hole, view along bundle axis):
 *
 *   col:  0    1    2
 *   r=0   •    •    •
 *   r=1   •   [_]   •
 *   r=2  [_]   •   [_]
 *
 * Expected: 6 panels at ±30°, 90°, ±150°, ±210°, 270°, ±330°.
 * Each panel should have ~4 contributing helices and similar widths (~6.5 nm).
 */
export function run6hbHC() {
  const cells = [
    [0, 0], [1, 0],   // left column (even-col)
    [0, 1], [2, 1],   // centre column (odd-col; row 1 is hole, row 2 is valid)
    [0, 2], [1, 2],   // right column (even-col)
  ]
  const positions = cells.map(([r, c]) => hcPos(r, c))
  const helixIds  = positions.map((_, i) => `h${i}`)
  const helixAxes = makeAxes(positions)
  return runExperiment('6hb HC ring', helixIds, helixAxes, 'HONEYCOMB')
}

/**
 * Exp 2 — 18hb HC elongated barrel
 *
 * 18 helices spanning 3 columns (cols 0–2) × 9 nominal rows (rows 0–8).
 * Holes are automatically excluded; exactly 18 valid cells remain.
 * The cross-section is elongated along V (Z axis).
 *
 * Expected: 6 panels.
 *   • 90° and 270° (axial end-caps of the long dimension): narrow (~3.9 nm).
 *   • ±30° / ±150° / ±210° / ±330° (long sides): wide (spanning most of the height).
 */
export function run18hbHC() {
  const cells     = hcGrid(0, 8, 0, 2)   // 6+6+6 = 18 valid cells
  const positions = cells.map(([r, c]) => hcPos(r, c))
  const helixIds  = positions.map((_, i) => `h${i}`)
  const helixAxes = makeAxes(positions)
  console.log('[18hbHC] cells:', cells.length, '— expected 18')
  return runExperiment('18hb HC elongated barrel', helixIds, helixAxes, 'HONEYCOMB')
}

/**
 * Exp 3 — 30hb HC platform (wide, flat)
 *
 * 30 helices in 15 columns (cols 0–14) × 3 nominal rows (rows 0–2).
 * Holes excluded; exactly 30 valid cells (8 even-cols × 2 + 7 odd-cols × 2).
 * The cross-section is wide along U (X axis) and narrow along V (Z axis).
 *
 * Expected: 6 panels.
 *   • 90° / 270° (top/bottom of the wide face): very wide (~27 nm), ~15 contributors.
 *   • ±30° / ±150° / ±210° / ±330° (short ends + corners): narrow (~3.4 nm), 2–4 contributors.
 */
export function run30hbPlatformHC() {
  const cells     = hcGrid(0, 2, 0, 14)  // 30 valid cells
  const positions = cells.map(([r, c]) => hcPos(r, c))
  const helixIds  = positions.map((_, i) => `h${i}`)
  const helixAxes = makeAxes(positions)
  console.log('[30hbPlatformHC] cells:', cells.length, '— expected 30')
  return runExperiment('30hb HC platform (wide)', helixIds, helixAxes, 'HONEYCOMB')
}

/**
 * Exp 4 — 2×6hb square lattice  (12 helices, 2 rows × 6 cols)
 *
 * 12 helices on a square lattice, arranged in a 2-row × 6-column grid.
 * SQ lattice has no holes — all 12 cells are valid.
 * Helix pitch = 2.25 nm in both directions.
 *
 * Cross-section schematic (• = helix):
 *
 *   col:  0    1    2    3    4    5
 *   r=0   •    •    •    •    •    •
 *   r=1   •    •    •    •    •    •
 *
 * Expected: 4 panels at 0°, 90°, 180°, 270°.
 *   •   0° / 180° (left/right ends):  narrow (~3.25 nm), 2 contributors each.
 *   •  90° / 270° (top/bottom faces): wide   (~14.75 nm), 6 contributors each.
 */
export function run2x6hbSQ() {
  const cells     = sqGrid(0, 1, 0, 5)   // 12 cells, all valid
  const positions = cells.map(([r, c]) => sqPos(r, c))
  const helixIds  = positions.map((_, i) => `h${i}`)
  const helixAxes = makeAxes(positions)
  return runExperiment('2×6hb SQ lattice (2 rows × 6 cols)', helixIds, helixAxes, 'SQUARE')
}

/**
 * Run all four experiments and report a pass/fail summary.
 * @returns {object[]}  array of per-experiment results
 */
export function runAll() {
  console.clear()
  console.log('%c━━━━  joint_panel_experiments.js  ━━━━', 'font-weight:bold; font-size:14px; color:#4488ff')
  console.log('%cLattice-based exterior panel algorithm — validation suite', 'color:#aaaaff')
  console.log('%c' + '─'.repeat(64), 'color:#555')
  console.log()

  const experiments = [
    { name: '6hb HC ring',          fn: run6hbHC          },
    { name: '18hb HC barrel',        fn: run18hbHC         },
    { name: '30hb HC platform',      fn: run30hbPlatformHC },
    { name: '2×6hb SQ lattice',      fn: run2x6hbSQ        },
  ]

  const results = experiments.map(({ fn }) => fn())

  // Summary table
  console.log('%c\n━━━  Summary  ━━━', 'font-weight:bold; color:#4488ff')
  console.table(
    experiments.map(({ name }, i) => ({
      experiment:     name,
      panels_found:   results[i].panels.length,
      expected:       results[i].pass ? results[i].panels.length : '?',
      status:         results[i].pass ? '✅ PASS' : '⚠️  MISMATCH',
    })),
  )
  const nPass = results.filter(r => r.pass).length
  console.log(
    `%c${nPass}/${results.length} passed`,
    `font-weight:bold; font-size:13px; color:${nPass === results.length ? '#44cc88' : '#ff4444'}`,
  )
  return results
}
