import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { getGeometry, getStraightGeometry, putNucleotideTransforms } from './client.js'
import { store } from '../state/store.js'

const axis = { helix_id: 'h', start: [0, 0, 0], end: [0, 0, 4], residue_transformed: true,
  segments: [{ bp_lo: 0, bp_hi: 11, start: [0, 5, 0], end: [0, 5, 4] }] }
const design = { id: 'axis-test', helices: [], strands: [], nucleotide_transforms: [], crossovers: [] }
beforeEach(() => { store.setState({ currentDesign: design, currentGeometry: [], currentHelixAxes: null, straightGeometry: null, straightHelixAxes: null }) })
afterEach(() => vi.unstubAllGlobals())
function respond(body) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, headers: { get: () => null }, json: async () => body })))
}
it('retains residue axis ownership on loading geometry and embedded straight geometry', async () => {
  respond({ nucleotides: [], helix_axes: [axis], straight_positions_by_helix: {}, straight_helix_axes: [axis] })
  await getGeometry()
  expect(store.getState().currentHelixAxes.h.residue_transformed).toBe(true)
  expect(store.getState().straightHelixAxes.h.residue_transformed).toBe(true)
})
it('retains residue axis ownership when fetching straight geometry', async () => {
  respond({ nucleotides: [], helix_axes: [axis] })
  await getStraightGeometry()
  expect(store.getState().straightHelixAxes.h.residue_transformed).toBe(true)
})
it('retains the moved segments on a partial edit and clears ownership when resetting', async () => {
  const body = { design, nucleotides: [], helix_axes: [axis], partial_geometry: true, changed_helix_ids: ['h'], straight_positions_by_helix: {}, straight_helix_axes: [axis] }
  respond(body)
  await putNucleotideTransforms([])
  expect(store.getState().currentHelixAxes.h.residue_transformed).toBe(true)
  expect(store.getState().currentHelixAxes.h.segments).toEqual(axis.segments)
  expect(store.getState().straightHelixAxes.h.residue_transformed).toBe(true)
  respond({ ...body, helix_axes: [{ ...axis, residue_transformed: undefined }] })
  await putNucleotideTransforms([])
  expect(store.getState().currentHelixAxes.h.residue_transformed).toBe(false)
})
