import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(resolve(process.cwd(), 'src/cadnano-editor/pathview.js'), 'utf8')

function fnBody(name) {
  const start = SOURCE.indexOf(`function ${name}(`)
  if (start < 0) return null
  const open = SOURCE.indexOf('{', start)
  let depth = 0
  for (let i = open; i < SOURCE.length; i++) {
    if (SOURCE[i] === '{') depth++
    else if (SOURCE[i] === '}' && --depth === 0) return SOURCE.slice(open, i + 1)
  }
  return null
}

describe('pathview responsiveness indexes', () => {
  it('uses a row-band index and one track bucket for point hit testing', () => {
    const hit = fnBody('_hitTest')
    expect(hit).toContain('_rowAtWY(wy)')
    expect(hit).toContain('_firstTrackEntryAtBp(hid, direction, bp)')
    expect(hit).not.toContain('for (const [hid, info] of _rowMap)')
    expect(hit).not.toContain('for (let si = 0; si < _design.strands.length; si++)')
  })

  it('limits lasso candidates by row bands and sorted track intervals', () => {
    const candidates = fnBody('_lassoDomainEntries')
    const strandLasso = fnBody('_hitTestLassoStrands')
    expect(candidates).toContain('_rowBands[mid].hi > ly0')
    expect(candidates).toContain('_trackEntriesOverlappingCells(')
    expect(strandLasso).toContain('_lassoDomainEntries(')
    expect(strandLasso).not.toContain('_design.strands')
  })

  it('shares one bounded descriptor index across arc clicks and lasso', () => {
    const build = fnBody('_ensureXoverArcHitIndex')
    const pointHit = fnBody('_hitTestArc')
    const lasso = fnBody('_hitTestLassoElements')
    expect(build).toContain('for (const xo of _design?.crossovers ?? [])')
    expect(build).toContain('for (const fl of _design?.forced_ligations ?? [])')
    expect(pointHit).toContain('_xoverArcHitBins.get(bucket)')
    expect(lasso).toContain('_xoverArcHitBins.get(bucket)')
    expect(pointHit).not.toContain('_design.crossovers')
    expect(pointHit).not.toContain('_design.forced_ligations')
  })

  it('resolves crossover drag and nick operations through immutable indexes', () => {
    expect(SOURCE).toContain('_xoversByKey.get(key) ?? []')
    expect(fnBody('_needsNick')).toContain('_firstTrackEntryAtBp(')
    expect(fnBody('_nickBpForDomain')).toContain('_strandEntryByDomain.get(dom)')
    expect(fnBody('_findLigation')).toContain('_nickTerminalsByTrack.get(')
  })
})
