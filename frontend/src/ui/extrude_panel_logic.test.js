/**
 * Unit tests for the Extrude tool's pure decision helpers.
 */
import { describe, it, expect } from 'vitest'
import {
  resolveDefaultPlane,
  dropdownStateForMode,
  axesVisibleForDesign,
  latticeLengthStepBp,
} from './extrude_panel_logic.js'

describe('resolveDefaultPlane', () => {
  it('falls back to XY when no plane is set', () => {
    expect(resolveDefaultPlane(null)).toBe('XY')
    expect(resolveDefaultPlane(undefined)).toBe('XY')
  })
  it('keeps the design plane when one is set', () => {
    expect(resolveDefaultPlane('XZ')).toBe('XZ')
    expect(resolveDefaultPlane('YZ')).toBe('YZ')
  })
})

describe('dropdownStateForMode', () => {
  it('new-bundle: interactive, shows the default plane', () => {
    expect(dropdownStateForMode('newBundle', null, 'XY')).toEqual({ value: 'XY', disabled: false })
    expect(dropdownStateForMode('newBundle', 'XZ', 'YZ')).toEqual({ value: 'YZ', disabled: false })
  })
  it('context modes: locked to the geometry plane', () => {
    for (const mode of ['segment', 'continuation', 'deformed']) {
      expect(dropdownStateForMode(mode, 'XZ', 'XY')).toEqual({ value: 'XZ', disabled: true })
    }
  })
  it('context modes fall back to the default plane when no context plane given', () => {
    expect(dropdownStateForMode('continuation', null, 'YZ')).toEqual({ value: 'YZ', disabled: true })
  })
})

describe('axesVisibleForDesign', () => {
  it('shows the triad for an empty (helix-less) design', () => {
    expect(axesVisibleForDesign({ helices: [] }, false)).toBe(true)
    expect(axesVisibleForDesign(null, false)).toBe(true)
    expect(axesVisibleForDesign(undefined, false)).toBe(true)
  })
  it('hides the triad once the design has helices', () => {
    expect(axesVisibleForDesign({ helices: [{ id: 'h' }] }, false)).toBe(false)
  })
  it('hides the triad in assembly mode regardless of helices', () => {
    expect(axesVisibleForDesign({ helices: [] }, true)).toBe(false)
  })
})

describe('latticeLengthStepBp', () => {
  it('steps by 8 bp on the square lattice', () => {
    expect(latticeLengthStepBp('SQUARE')).toBe(8)
  })
  it('steps by 7 bp on honeycomb (and any non-square default)', () => {
    expect(latticeLengthStepBp('HONEYCOMB')).toBe(7)
    expect(latticeLengthStepBp(null)).toBe(7)
    expect(latticeLengthStepBp(undefined)).toBe(7)
  })
})

