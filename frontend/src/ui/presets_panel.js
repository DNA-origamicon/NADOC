/**
 * Presets panel — one-click buttons for standard DNA origami bundle structures.
 *
 * Each preset is a script (compatible with the paste-script format) that
 * rebuilds a named structure from scratch via sequential API calls.
 *
 * Cell coordinates use our internal (row, col) honeycomb lattice system:
 *
 *   6HB  — 6 helices arranged in a hexagonal ring around the central hole at (1,1).
 *   18HB — 18 helices filling a 4-row × 6-col grid (rows 0–3, cols 0–5) with
 *           holes excluded by the (row + col%2) % 3 == 2 rule.
 *
 * The 42bp variants are single-extrusion structures (one bundle step).
 * The 420bp variants use 10 × 42bp segments: one initial bundle plus nine
 * bundle_continuation steps, mirroring the manual user workflow of clicking
 * successive blunt ends to extend the structure.
 */

// ── Honeycomb cell lists ───────────────────────────────────────────────────────

// 6-helix bundle: 6 cells forming a hexagonal ring around hole (1,1).
const CELLS_6HB = [
  [0, 0], [0, 1], [1, 0],
  [2, 1], [0, 2], [1, 2],
]

// 18-helix bundle: custom asymmetric layout (see drawings/honeycomb_proposed.png).
const CELLS_18HB = [
  [0, 0], [0, 1], [1, 0],
  [0, 2], [1, 2], [2, 1],
  [3, 1], [3, 0], [4, 0],
  [5, 1], [4, 2], [3, 2],
  [3, 3], [3, 4], [3, 5],
  [2, 5], [1, 4], [2, 3],
]

// ── Preset definitions ─────────────────────────────────────────────────────────

export const PRESETS = [
  {
    id:    '6hb-42',
    label: '6HB · 42bp',
    script: {
      name:  '6HB 42bp',
      steps: [
        { type: 'bundle', cells: CELLS_6HB, length_bp: -42, plane: 'XY' },
      ],
    },
  },
  {
    id:    '18hb-42',
    label: '18HB · 42bp',
    script: {
      name:  '18HB 42bp',
      steps: [
        { type: 'bundle', cells: CELLS_18HB, length_bp: -42, plane: 'XY' },
      ],
    },
  },
  {
    id:    '6hb-420',
    label: '6HB · 420bp',
    script: {
      name:  '6HB 420bp',
      steps: [
        { type: 'bundle', cells: CELLS_6HB, length_bp: -420, plane: 'XY' },
      ],
    },
  },
  {
    id:    '18hb-420',
    label: '18HB · 420bp',
    script: {
      name:  '18HB 420bp',
      steps: [
        { type: 'bundle', cells: CELLS_18HB, length_bp: -420, plane: 'XY' },
      ],
    },
  },
]

/** Keyed map of preset scripts, e.g. PRESET_SCRIPTS['6hb-42'] */
export const PRESET_SCRIPTS = Object.fromEntries(PRESETS.map(p => [p.id, p.script]))

// ── Panel initialisation ───────────────────────────────────────────────────────

/**
 * Populate #presets-grid with one button per preset.
 * @param {function} runScript  — from createScriptRunner()
 */
export function initPresetsPanel(runScript) {
  const grid = document.getElementById('presets-grid')
  if (!grid) return

  let _running = false

  for (const preset of PRESETS) {
    const btn = document.createElement('button')
    btn.className   = 'preset-btn'
    btn.id          = `preset-${preset.id}`
    btn.textContent = preset.label

    btn.addEventListener('click', async () => {
      if (_running) return
      _running = true
      document.querySelectorAll('.preset-btn').forEach(b => b.classList.add('running'))

      try {
        await runScript(preset.script)
      } catch (err) {
        console.error('Preset script error:', err)
        alert(`Preset failed: ${err.message}`)
      } finally {
        _running = false
        document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('running'))
      }
    })

    grid.appendChild(btn)
  }
}
