import { describe, it, expect } from 'vitest'
import {
  STYLE_PRESETS, CUSTOM_STYLE, resolveStyle, detectStyle, styleLabel,
} from './style_presets.js'
import { DEFAULT_PHOTO_SETTINGS } from '../photo_renderer.js'

describe('resolveStyle', () => {
  it('returns null for an unknown style', () => {
    expect(resolveStyle('nope')).toBeNull()
    expect(resolveStyle(CUSTOM_STYLE)).toBeNull()
  })

  it('strips the UI-only label so it can never reach the persisted settings', () => {
    const patch = resolveStyle('publication')
    expect(patch).not.toHaveProperty('label')
    expect(STYLE_PRESETS.publication.label).toBe('Publication (figure)')
  })

  it('publication turns the figure controls ON', () => {
    const p = resolveStyle('publication')
    expect(p.outline).toBe(true)
    expect(p.depthCue).toBe(true)
    expect(p.ao).toBe(true)
    expect(p.parallel).toBe(true)
    expect(p.lighting).toBe('ambient')
    expect(p.full).toBe('flat')
    expect(p.cylinders).toBe('flat')
    expect(p.surface).toBe('flat')
    expect(p.atomistic).toBe('cpk-flat')
  })

  it('publication turns every photoreal knob OFF — that is the whole point', () => {
    const p = resolveStyle('publication')
    expect(p.bloom).toBe(false)
    expect(p.envEffect).toBe('none')
    expect(p.environment).toBe('off')
    expect(p.environmentBackground).toBe(false)
    expect(p.floor).toBe('off')
    expect(p.floorGrid).toBe(false)
    expect(p.fluorophoreEmissive).toBe(false)
    expect(p.sun).toBe(false)
    expect(p.pathTracing).toBe(false)
    expect(p.translucency).toBe(0)
  })

  it('publication2 = soft occlusion look: AO on, but NO outline and a directional key', () => {
    const p = resolveStyle('publication2')
    expect(STYLE_PRESETS.publication2.label).toBe('Publication 2 (soft occlusion)')
    // Its defining differences from `publication`:
    expect(p.outline).toBe(false)        // separation comes from occlusion, not contours
    expect(p.depthCue).toBe(false)
    expect(p.lighting).toBe('scientific')// a soft top key, not occlusion-only 'ambient'
    expect(p.parallel).toBe(false)       // moderate perspective, not the near-parallel lens
    expect(p.bgType).toBe('black')
    // Strong ambient occlusion is the primary shading cue.
    expect(p.ao).toBe(true)
    expect(p.ssao).toBe(false)
    expect(p.aoIntensity).toBeGreaterThan(1.0)
    // Same non-photoreal matte materials as publication.
    expect(p.full).toBe('flat')
    expect(p.surface).toBe('flat')
    expect(p.atomistic).toBe('cpk-flat')
    // Photoreal knobs stay off.
    expect(p.bloom).toBe(false)
    expect(p.pathTracing).toBe(false)
    expect(p.floor).toBe('off')
  })

  it('publication2 is distinguishable from publication (detectStyle picks the right one)', () => {
    expect(detectStyle({ ...DEFAULT_PHOTO_SETTINGS, ...resolveStyle('publication2') }))
      .toBe('publication2')
    expect(detectStyle({ ...DEFAULT_PHOTO_SETTINGS, ...resolveStyle('publication') }))
      .toBe('publication')
  })

  it('studio restores the photoreal look and turns the figure controls off', () => {
    const p = resolveStyle('studio')
    expect(p.outline).toBe(false)
    expect(p.depthCue).toBe(false)
    expect(p.ao).toBe(false)
    expect(p.parallel).toBe(false)
    expect(p.lighting).toBe('studio')
    expect(p.environment).toBe('room')   // metals need an env or they render dark
    expect(p.ssao).toBe(true)
  })

  it('every key a preset sets is a real setting (no typos that would silently no-op)', () => {
    for (const name of Object.keys(STYLE_PRESETS)) {
      for (const key of Object.keys(resolveStyle(name))) {
        expect(DEFAULT_PHOTO_SETTINGS, `${name}.${key}`).toHaveProperty(key)
      }
    }
  })
})

describe('detectStyle', () => {
  it('recognises a settings object that a preset was applied to', () => {
    const settings = { ...DEFAULT_PHOTO_SETTINGS, ...resolveStyle('publication') }
    expect(detectStyle(settings)).toBe('publication')
  })

  it('falls back to custom as soon as one preset-owned key differs', () => {
    const settings = { ...DEFAULT_PHOTO_SETTINGS, ...resolveStyle('publication'), bloom: true }
    expect(detectStyle(settings)).toBe(CUSTOM_STYLE)
  })

  it('still matches when a key NO preset has an opinion about changes', () => {
    const settings = {
      ...DEFAULT_PHOTO_SETTINGS,
      ...resolveStyle('publication'),
      mistNoiseSpeed: 0.7,   // publication says nothing about wispiness
    }
    expect(detectStyle(settings)).toBe('publication')
  })

  it('returns custom for null/empty settings', () => {
    expect(detectStyle(null)).toBe(CUSTOM_STYLE)
    expect(detectStyle({})).toBe(CUSTOM_STYLE)
  })
})

describe('styleLabel', () => {
  it('names known styles and calls everything else Custom', () => {
    expect(styleLabel('publication')).toBe('Publication (figure)')
    expect(styleLabel('studio')).toBe('Studio (product render)')
    expect(styleLabel(CUSTOM_STYLE)).toBe('Custom')
    expect(styleLabel('bogus')).toBe('Custom')
  })
})
