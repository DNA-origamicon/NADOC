import { beforeEach, expect, it } from 'vitest'
import { DEFAULTS, readPreferences, writePreferences, validatePreferences, importPreferences, exportPreferences } from './preferences.js'
beforeEach(() => localStorage.clear())
it('retains defaults and migrates the existing preview preference', () => {
  expect(readPreferences()).toEqual(DEFAULTS)
  localStorage.setItem('NADOC_EXTRUDE_PREVIEW', 'false')
  expect(readPreferences().preview).toBe(false)
})
it('rejects invalid imports before changing saved preferences', () => {
  writePreferences({ textScale: 1.5 })
  for (const bad of [{ textScale: 4 }, { autosave: 'false' }, { theme: 'unknown' }, { __unknown: 1 }, { textScale: NaN }]) expect(() => validatePreferences(bad)).toThrow()
  expect(() => importPreferences('{"version":2}')).toThrow()
  expect(readPreferences().textScale).toBe(1.5)
})
it('round trips only browser preferences without machine paths or simulation data', () => {
  const text = exportPreferences({ ...DEFAULTS, textScale: 1.25 })
  expect(importPreferences(text).textScale).toBe(1.25)
  expect(text).not.toContain('runDir')
  expect(() => exportPreferences({ runDir: '/tmp' })).toThrow()
})
it('rolls back the entire settings transaction if a directory cannot be persisted', () => {
  const entries = new Map()
  const storage = {
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => { if (key === 'nadoc.runDir.oxdna') throw new Error('quota'); entries.set(key, value) },
    removeItem: key => entries.delete(key),
  }
  expect(() => writePreferences({ textScale: 1.25 }, storage, { namd: '/data/md', oxdna: '/data/oxdna' })).toThrow('quota')
  expect(entries.size).toBe(0)
})
