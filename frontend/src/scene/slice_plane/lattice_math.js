// Pure lattice-cell math helpers extracted from slice_plane.js (Refactor 09-A).
// Honeycomb (cadnano2 system) + square lattice cell positions.
// Leaf module: imports nothing from slice_plane.js or other slice_plane/* modules.

import * as THREE from 'three'
import {
  HONEYCOMB_LATTICE_RADIUS,
  HONEYCOMB_COL_PITCH,
  HONEYCOMB_ROW_PITCH,
  SQUARE_HELIX_SPACING,
} from '../../constants.js'

// ── Cell helpers ──────────────────────────────────────────────────────────────

// Always-positive modulo (matches Python's % for negative operands)
export function _mod(n, m) { return ((n % m) + m) % m }

// ── Honeycomb (cadnano2 system: all cells valid, (row+col)%2 parity) ──
// x = col × COL_PITCH + ox, y = row × ROW_PITCH + stagger + oy.
// ox/oy are the lattice origin offset derived from actual helix physical positions.
export function isValidHoneycombCell(_row, _col) { return true }  // no hole cells in cadnano2

export function honeycombCellWorldPos(row, col, plane, offset, ox = 0, oy = 0) {
  const lx  = col * HONEYCOMB_COL_PITCH + ox
  const odd = (((row + col) % 2) + 2) % 2   // 1 if odd parity, 0 if even
  const ly  = row * HONEYCOMB_ROW_PITCH + (odd ? HONEYCOMB_LATTICE_RADIUS : 0) + oy
  if (plane === 'XY') return new THREE.Vector3(lx, ly, offset)
  if (plane === 'XZ') return new THREE.Vector3(lx, offset, ly)
  /* YZ */            return new THREE.Vector3(offset, lx, ly)
}

// ── Square lattice ──
// All cells are valid (checkerboard of FORWARD/REVERSE, no holes).
export function isValidSquareCell(_row, _col) { return true }  // eslint-disable-line no-unused-vars

export function squareCellWorldPos(row, col, plane, offset, ox = 0, oy = 0) {
  const lx = col * SQUARE_HELIX_SPACING + ox
  const ly = row * SQUARE_HELIX_SPACING + oy
  if (plane === 'XY') return new THREE.Vector3(lx, ly, offset)
  if (plane === 'XZ') return new THREE.Vector3(lx, offset, ly)
  /* YZ */            return new THREE.Vector3(offset, lx, ly)
}
