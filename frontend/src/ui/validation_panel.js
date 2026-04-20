/**
 * Validation panel UI — wires HTML buttons to helix renderer mode switches
 * and moves the camera to the canonical viewpoint for each checkpoint.
 */

const PROMPTS = {
  normal: `Select a validation checkpoint to begin.`,

  'V1.1': `
    <strong>Handedness check</strong><br><br>
    Looking <em>down the helix axis from above</em> (camera at +Z end, looking
    toward the helix start).<br><br>
    The <span style="color:#00e676">green spheres / cubes</span> are the
    FORWARD strand backbone beads. The green cube is the 5′ end (bp 0).
    The REVERSE strand is dimmed.<br><br>
    ▶ For right-handed B-DNA, the green beads should spiral
    <strong>COUNTERCLOCKWISE</strong> as you watch them recede into the screen.<br><br>
    The cone connectors show the 5′→3′ direction of travel (tip points toward next bead).
    Does the green strand spiral counterclockwise?
    If clockwise, report <span class="key">wrong</span>.
  `,

  'V1.2': `
    <strong>Rise per base pair</strong><br><br>
    The two <span style="color:#ff3333">red enlarged spheres</span> are the
    FORWARD strand backbone beads at <strong>bp 0</strong> (lower, near axis
    start) and <strong>bp 1</strong> (one step above).<br><br>
    The label shows the <strong>axial rise</strong> — the distance between them
    measured along the helix axis direction only (projection onto axis_tangent),
    not the full 3D chord distance which includes twist.<br><br>
    ▶ The axial rise must be exactly <strong>0.334 nm</strong>.<br><br>
    Does the label read 0.3340 nm?
  `,

  'V1.3': `
    <strong>Base-normal direction</strong><br><br>
    At bp 0 on the FORWARD strand:<br>
    • <span style="color:#ff3333">Red sphere</span> = backbone bead.<br>
    • <span style="color:#ffdd00">Yellow slab</span> = base slab.<br>
    • <span style="color:#ffdd00">Yellow arrow</span> = base-normal direction,
      drawn at 5× length.<br><br>
    ▶ The yellow arrow should point <strong>FROM the FORWARD backbone bead
    TOWARD the REVERSE backbone bead</strong> (not toward the helix axis center).
    In B-DNA the two strands are offset by the minor groove (~120°), so the
    base normal is a cross-strand vector, not a radial.<br><br>
    Does the yellow arrow point toward the other strand's backbone?
    If it points directly at the axis center, report <span class="key">wrong</span>.
  `,

  'V1.4': `
    <strong>Major/minor groove geometry</strong><br><br>
    At bp 10:<br>
    • <span style="color:#ff3333">Red sphere</span> = FORWARD backbone bead.<br>
    • <span style="color:#3399ff">Blue sphere</span> = REVERSE backbone bead.<br>
    • White line connects them.<br><br>
    ▶ In B-DNA the two strands are <strong>NOT</strong> diametrically opposite
    (180°). The REVERSE strand is offset by ~120° (minor groove) from the
    FORWARD strand. The white line should <strong>NOT</strong> pass through the
    helix axis — it should be offset to one side, subtending the minor groove.
    Backbone-to-backbone distance should be ~1.73 nm (√3 × helix_radius).<br><br>
    Does the white line miss the axis arrow?
    If it passes through the axis, report <span class="key">wrong</span>.
  `,

  'V2.1': `
    <strong>Selection identity</strong><br><br>
    Click any backbone bead in the scene.<br><br>
    ▶ The clicked bead should turn <strong>WHITE</strong> and scale 1.5×.<br>
    ▶ The <em>Properties</em> panel at the top of this sidebar should immediately
    show the correct <em>helix_id</em>, <em>bp_index</em>, <em>direction</em>,
    and <em>strand_id</em> for that nucleotide.<br><br>
    Click empty space to deselect (bead returns to its strand color).<br><br>
    Does clicking a bead update the Properties panel with the correct values?
    If the panel stays blank or shows wrong data, report <span class="key">wrong</span>.
  `,

  'V2.2': `
    <strong>Strand termini</strong><br><br>
    The <span style="color:#ffffff">WHITE enlarged beads</span> are all strand
    5′ and 3′ ends.<br><br>
    Are all strand ends highlighted in white?
    If some ends are missing or the wrong color, report <span class="key">wrong</span>.
  `,

  'V2.3': `
    <strong>Strand polarity</strong><br><br>
    • <span style="color:#00e676">Green enlarged beads</span> = 5′ ends of every strand.<br>
    • <span style="color:#ff3333">Red enlarged beads</span> = 3′ ends of every strand.<br><br>
    The cone connectors already indicate 5′→3′ direction (tip points toward the
    next nucleotide in the 5′→3′ chain).<br><br>
    ▶ For the <span style="color:#00e676">FORWARD scaffold</span>:
    5′ end (green) should be at <strong>bp 0</strong> (near the helix axis start,
    bottom of the helix). 3′ end (red) at the top (bp 41).<br><br>
    ▶ For the <span style="color:#29b6f6">REVERSE staple</span>:
    5′ end (green) at the top (bp 41), 3′ end (red) at bp 0.<br><br>
    Are 5′ ends green and 3′ ends red, at the correct ends of each strand?
    If swapped, report <span class="key">wrong</span>.
  `,

  'V2.4': `
    <strong>Scaffold continuity</strong><br><br>
    The <span style="color:#00e676">scaffold strand</span> is shown at full
    brightness; all other strands are dimmed.<br><br>
    • <span style="color:#ff00ff">Magenta enlarged beads</span> = scaffold strand
    termini (5′ and 3′ ends). These are <em>nick sites</em> — where the scaffold
    strand starts and ends.<br><br>
    ▶ In a complete single-scaffold design, there should be exactly
    <strong>one pair</strong> of magenta beads (one 5′ and one 3′ terminus).
    A continuous scaffold forms a single closed loop or linear path through the
    entire structure. Additional nick sites indicate scaffold breaks.<br><br>
    How many magenta beads are visible?
    If more than 2, the scaffold has internal breaks — report <span class="key">wrong</span>.
  `,
}

// Camera position and OrbitControls target for each mode.
// Helix runs from z=0 to z≈14.028 nm along the Z axis.
const CAMERA_PRESETS = {
  normal: { pos: [6, 3, 7],    target: [0, 0, 7] },
  // V1.1: look from high +Z toward the helix start at origin
  'V1.1': { pos: [0, 0, 26],  target: [0, 0, 7] },
  // V1.2: close up on bp 0 and bp 1 (near z=0)
  'V1.2': { pos: [3, 2, 0.7], target: [0, 0, 0.5] },
  // V1.3: close up on bp 0
  'V1.3': { pos: [3, 2, 0.2], target: [0, 0, 0] },
  // V1.4: side view near z ≈ 10 × 0.334 ≈ 3.34 nm
  'V1.4': { pos: [5, 1, 3.5], target: [0, 0, 3.5] },
  // V2.1: standard side view — user clicks beads to test selection
  'V2.1': { pos: [6, 3, 7],   target: [0, 0, 7] },
  // V2.2: full-helix side view to see all termini
  'V2.2': { pos: [6, 3, 7],   target: [0, 0, 7] },
  // V2.3: full-helix side view to see both 5′ and 3′ ends
  'V2.3': { pos: [6, 3, 7],   target: [0, 0, 7] },
  // V2.4: full-helix side view to see scaffold path and nick sites
  'V2.4': { pos: [6, 3, 7],   target: [0, 0, 7] },
}

export function initValidationPanel(helixCtrl, camera, controls) {
  const btns      = document.querySelectorAll('.checkpoint-btn')
  const promptBox = document.getElementById('prompt-box')
  const resetBtn  = document.getElementById('reset-btn')

  let currentMode = 'normal'

  function applyCamera(mode) {
    const p = CAMERA_PRESETS[mode]
    if (!p) return
    camera.position.set(...p.pos)
    controls.target.set(...p.target)
    controls.update()
  }

  function setMode(mode) {
    currentMode = mode
    btns.forEach(b => b.classList.toggle('active', b.dataset.mode === mode))
    promptBox.innerHTML = `<p>${PROMPTS[mode] ?? ''}</p>`
    helixCtrl.setMode(mode)
    applyCamera(mode)
  }

  btns.forEach(btn => btn.addEventListener('click', () => setMode(btn.dataset.mode)))
  resetBtn.addEventListener('click', () => applyCamera(currentMode))

  setMode('normal')
}
