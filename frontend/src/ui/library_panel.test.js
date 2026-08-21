// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  hasLargeSimulationData,
  mergeLibraryDiskUsage,
  readLibraryCache,
  writeLibraryCache,
} from './library_panel.js'

describe('hasLargeSimulationData', () => {
  const halfGb = 0.5 * 1024 ** 3

  it('only flags NAMD/oxDNA data strictly larger than 0.5 GB', () => {
    expect(hasLargeSimulationData(halfGb - 1)).toBe(false)
    expect(hasLargeSimulationData(halfGb)).toBe(false)
    expect(hasLargeSimulationData(halfGb + 1)).toBe(true)
  })

  it('uses a selector specific enough to beat the later accessibility size rule', () => {
    const html = readFileSync(`${process.cwd()}/index.html`, 'utf8')
    expect(html).toContain('.lib-row-size.lib-row-size-sim')
  })
})

describe('mergeLibraryDiskUsage', () => {
  it('enriches parts without changing assemblies or folders', () => {
    const entries = [
      { type: 'part', path: 'Parts/a.nadoc', size_bytes: 100 },
      { type: 'assembly', path: 'asm.nass', size_bytes: 50 },
      { type: 'folder', path: 'Parts', size_bytes: 0 },
    ]
    const out = mergeLibraryDiskUsage(entries, { 'Parts/a.nadoc': 900 })
    expect(out[0]).toMatchObject({ sim_bytes: 900, disk_bytes: 1000 })
    expect(out[1]).toBe(entries[1])
    expect(out[2]).toBe(entries[2])
  })

  it('treats a part with no jobs as file-only disk usage', () => {
    const out = mergeLibraryDiskUsage(
      [{ type: 'part', path: 'a.nadoc', size_bytes: 123 }],
      {},
    )
    expect(out[0]).toMatchObject({ sim_bytes: 0, disk_bytes: 123 })
  })
})

describe('library cache', () => {
  it('round-trips the last file list for immediate reload rendering', () => {
    const storage = new Map()
    const adapter = {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    }
    const entries = [{ type: 'part', path: 'cached.nadoc' }]
    expect(writeLibraryCache(entries, adapter)).toBe(true)
    expect(readLibraryCache(adapter)).toEqual(entries)
  })

  it('ignores corrupt cached data', () => {
    expect(readLibraryCache({ getItem: () => '{bad json' })).toEqual([])
  })
})
