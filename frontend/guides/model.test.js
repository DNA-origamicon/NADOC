import { test } from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_GUIDE_MODEL, guideCells } from './model.js'

test('default footprint is exactly three rows and six columns on a square lattice', () => {
  assert.deepEqual(DEFAULT_GUIDE_MODEL, { lattice: 'SQUARE', rows: 3, columns: 6 })
  const cells = guideCells()
  assert.equal(cells.length, 18)
  assert.equal(new Set(cells.map(c => c.join(','))).size, 18)
  assert.deepEqual([...new Set(cells.map(c => c[0]))], [0, 1, 2])
  assert.deepEqual([...new Set(cells.map(c => c[1]))], [1, 2, 3, 4, 5, 6])
})

test('moving the footprint preserves its dimensions', () => {
  assert.deepEqual(guideCells(4, -2)[0], [4, -2])
  assert.deepEqual(guideCells(4, -2).at(-1), [6, 3])
})
