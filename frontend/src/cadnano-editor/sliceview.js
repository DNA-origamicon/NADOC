/**
 * Sliceview — SVG lattice grid for helix activation/deactivation.
 *
 * Renders an HC or SQ lattice grid.  Occupied cells (active helices) are
 * filled; empty cells are hollow.  Clicking an empty cell adds a helix;
 * clicking an occupied cell removes it.
 *
 * Phase 1 stub — renders the SVG container and wires up the design.
 * Full HC/SQ rendering is implemented in Commit 3.
 */

export function initSliceview(svgEl, { onAddHelix, onRemoveHelix }) {
  svgEl.setAttribute('width',  '200')
  svgEl.setAttribute('height', '200')

  // Placeholder text until Commit 3 implements real rendering
  const text = document.createElementNS('http://www.w3.org/2000/svg', 'text')
  text.setAttribute('x', '100')
  text.setAttribute('y', '100')
  text.setAttribute('text-anchor', 'middle')
  text.setAttribute('fill', '#444')
  text.setAttribute('font-size', '11')
  text.setAttribute('font-family', 'Courier New, monospace')
  text.textContent = 'Sliceview loading…'
  svgEl.appendChild(text)

  return {
    /**
     * Redraw the slice grid for the given design.
     * @param {object|null} design
     */
    update(design) {
      // Implemented in Commit 3
      if (design) {
        text.textContent = `${design.helices?.length ?? 0} helix(es)`
      }
    },
  }
}
