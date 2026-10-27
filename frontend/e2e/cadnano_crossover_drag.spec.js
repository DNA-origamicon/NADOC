import { test, expect } from '@playwright/test'

// Real canvas and pointer handlers; observation-only probe, no saved documents.
for (const [lattice, scaffold, original, delta, expected] of [
  ['SQUARE', true, 0, 3, 5],
  ['SQUARE', true, 0, -7, -5],
  ['SQUARE', false, 0, 17, 32],
  ['HONEYCOMB', true, 2, 8, 12],
]) {
  test(`${lattice} ${scaffold ? 'scaffold' : 'staple'} crossover drag by ${delta} bp`, async ({ page }) => {
    await page.route('**/crossover-drag-test', route => route.fulfill({ contentType: 'text/html',
      body: '<body style="margin:0"><div id="host" style="width:1200px;height:600px"><canvas></canvas></div></body>' }))
    await page.route('**/src/cadnano-editor/pathview.js', async route => {
      const response = await route.fetch()
      await route.fulfill({ response, body: (await response.text()).replace('  // ── Public interface', `
  window.dragProbe = {
    state: () => ({ active: _xoverDragActive, snap: _xoverDragSnapBp, deltas: _xoverDragValidDeltas }),
    point: (bp, track = false) => {
      const xo = _design.crossovers[0], a = _rowMap.get(xo.half_a.helix_id), b = _rowMap.get(xo.half_b.helix_id)
      const ya = xo.half_a.strand === 'FORWARD' ? a.fwdY : a.revY
      const yb = xo.half_b.strand === 'FORWARD' ? b.fwdY : b.revY
      const bow = _xoverBowDir(bp, ${scaffold}) * Math.max(BP_W * .27, Math.abs(yb - ya) * .07)
      return { x: (_bpCenterX(bp) + (track ? 0 : bow / 2)) * _zoom + _panX,
        y: (track ? ya - CELL_H / 2 - 3 : (ya + yb) / 2) * _zoom + _panY,
        step: BP_W * _zoom }
    },
  }
  // ── Public interface`) })
    })
    await page.goto('/crossover-drag-test')
    await page.evaluate(async ({ lattice, scaffold, original }) => {
      const { initPathview } = await import('/src/cadnano-editor/pathview.js')
      const forward = scaffold ? 'FORWARD' : 'REVERSE', reverse = scaffold ? 'REVERSE' : 'FORWARD'
      const design = { lattice_type: lattice,
        helices: ['a', 'b'].map((id, i) => ({ id, grid_pos: [0, i], bp_start: -64, length_bp: 192 })),
        strands: [{ id: 'strand', strand_type: scaffold ? 'scaffold' : 'staple', domains: [
          { helix_id: 'a', direction: forward, start_bp: -64, end_bp: original },
          { helix_id: 'b', direction: reverse, start_bp: original, end_bp: -64 },
        ] }],
        crossovers: [{ id: 'xo', half_a: { helix_id: 'a', index: original, strand: forward },
          half_b: { helix_id: 'b', index: original, strand: reverse } }],
      }
      window.moves = []
      const view = initPathview(document.querySelector('canvas'), document.querySelector('#host'), {
        onMoveCrossover: (id, bp) => window.moves.push({ id, bp }),
      })
      view.update(design); view.setTool('select'); view.fitToContent()
    }, { lattice, scaffold, original })
    const start = await page.evaluate(bp => window.dragProbe.point(bp), original)
    await page.mouse.move(start.x, start.y)
    await page.mouse.down()
    await expect.poll(() => page.evaluate(() => window.dragProbe.state().active)).toBe(true)
    await page.mouse.move(start.x + delta * start.step, start.y, { steps: 5 })
    await expect.poll(() => page.evaluate(() => window.dragProbe.state().snap)).toBe(expected)
    const targets = await page.evaluate(({ original, expected }) => {
      const ds = window.dragProbe.state().deltas, delta = expected - original
      return [...ds.filter(d => d < delta).slice(-2), ...ds.filter(d => d > delta).slice(0, 2)].map(d => original + d)
    }, { original, expected })
    expect(targets).toHaveLength(4)
    // Verify actual rendered dots and a negative control between locations.
    await expect.poll(() => page.evaluate(targets => {
      const ctx = document.querySelector('canvas').getContext('2d')
      const blue = bp => {
        const p = window.dragProbe.point(bp, true)
        const data = ctx.getImageData(Math.round(p.x) - 2, Math.round(p.y) - 2, 5, 5).data
        return Array.from({ length: 25 }, (_, i) => i * 4).some(i => data[i] === 0 && data[i + 1] === 95 && data[i + 2] === 160)
      }
      return targets.every(blue) && !blue((targets[1] + targets[2]) / 2)
    }, targets)).toBe(true)
    await page.mouse.up()
    expect(await page.evaluate(() => window.moves)).toEqual([{ id: 'xo', bp: expected }])
  })
}
