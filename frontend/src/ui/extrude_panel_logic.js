/**
 * Pure decision helpers for the Extrude tool / sidebar panel.
 *
 * Kept free of DOM / THREE / store so they can be unit-tested directly. The
 * stateful wiring lives in `extrude_panel.js`.
 */

/**
 * The plane a fresh new-bundle extrude should default to: the design's last-used
 * plane if one is set, else XY (helices along +Z).
 * @param {('XY'|'XZ'|'YZ'|null|undefined)} currentPlane
 * @returns {'XY'|'XZ'|'YZ'}
 */
export function resolveDefaultPlane(currentPlane) {
  return currentPlane ?? 'XY'
}

/**
 * The "Extrude from" dropdown's value + disabled state for a given extrude mode.
 *
 * - 'newBundle' → the user picks an origin plane, so the dropdown is interactive
 *   and shows the default plane.
 * - 'segment' | 'continuation' | 'deformed' → the plane is locked by the existing
 *   geometry (the helix end / deformed frame), so the dropdown is a disabled
 *   read-only reflection of that context plane. This keeps "only origin planes are
 *   valid" true for every case where the dropdown is actually interactive.
 *
 * @param {'newBundle'|'segment'|'continuation'|'deformed'} mode
 * @param {('XY'|'XZ'|'YZ'|null|undefined)} contextPlane  the geometry-locked plane (non-newBundle modes)
 * @param {'XY'|'XZ'|'YZ'} defaultPlane
 * @returns {{ value: 'XY'|'XZ'|'YZ', disabled: boolean }}
 */
export function dropdownStateForMode(mode, contextPlane, defaultPlane) {
  if (mode === 'newBundle') return { value: defaultPlane, disabled: false }
  return { value: contextPlane ?? defaultPlane, disabled: true }
}

/**
 * The lattice-aware step (in bp) the extrude length should change by when the user
 * presses the arrow keys in the length field. Honeycomb crossovers repeat every 7 bp
 * (21/3) and square every 8 bp (32/4), so stepping by 7/8 keeps the length on the
 * lattice's natural crossover period.
 * @param {('SQUARE'|'HONEYCOMB'|string|null|undefined)} latticeType
 * @returns {number} 8 for SQUARE, 7 otherwise
 */
export function latticeLengthStepBp(latticeType) {
  return latticeType === 'SQUARE' ? 8 : 7
}

/**
 * Whether the world-origin XYZ axis triad should be shown for a given design.
 * The triad marks the origin of an EMPTY part so the user has an orientation
 * reference before extruding. A populated part or an assembly hides it (its own
 * geometry is the reference).
 * @param {object|null|undefined} design
 * @param {boolean} assemblyActive
 * @returns {boolean}
 */
export function axesVisibleForDesign(design, assemblyActive) {
  if (assemblyActive) return false
  return (design?.helices?.length ?? 0) === 0
}
