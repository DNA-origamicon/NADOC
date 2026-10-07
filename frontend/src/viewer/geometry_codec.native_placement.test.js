// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { expandCompactNucleotides, positionUpdateLookup } from './geometry_codec.js'
import { replaceNativePlacement } from './native_placement.js'

const compact = () => ({ h: { FORWARD: {
  bp: [2, 2], bb: [[.84, 0, 0], [.84, 0, .167]], bs: [[.3, 0, 0], [.3, 0, .167]],
  bn: [[-1, 0, 0], [-1, 0, 0]], at: [[0, 0, 1], [0, 0, 1]],
  sp: [[.5, 0, 0], [.5, 0, .167]], sq: [[-.5, .5, .5, .5], [-.5, .5, .5, .5]],
  pv: ['native-full-o5-v1', 'native-full-o5-v1'],
} } })

describe('[native-placement] compact geometry contract', () => {
  it('keeps slab authority and inserted site identity through both full and diff codecs', () => {
    const payload = compact(), full = expandCompactNucleotides(payload), diff = positionUpdateLookup(payload)
    for (let i = 0; i < 2; i++) {
      expect(full[i]).toMatchObject(diff.get(`h:2:FORWARD:${i}`))
      expect(full[i].slab_position).toBe(payload.h.FORWARD.sp[i])
      expect(full[i].placement_source).toBe('native-full-o5-v1')
      expect(full[i].copy_k).toBe(i)
    }
    expect(full[0].slab_position).not.toEqual(full[1].slab_position)
  })

  it.each(['bb', 'sp', 'sq', 'pv'])('rejects missing %s in both codecs', field => {
    const payload = compact(); delete payload.h.FORWARD[field]
    expect(() => expandCompactNucleotides(payload)).toThrow()
    expect(() => positionUpdateLookup(payload)).toThrow(/DNA positioning could not be verified/)
  })

  it('does not accept stale slab fields from a prior record when patching', () => {
    const target = expandCompactNucleotides(compact())[0]
    const update = { ...target, backbone_position: [7, 8, 9] }; delete update.slab_position
    expect(() => replaceNativePlacement(target, update)).toThrow(/DNA positioning could not be verified/)
    expect(target.backbone_position).toEqual([.84, 0, 0])
  })

  it('copies explicit slabless extension and modification poses without inventing slabs', () => {
    for (const source of ['native-full-extension-v1', 'chemical-modification-v1']) {
      const target = { helix_id: '__ext_e', bp_index: 0, direction: 'FORWARD', extension_id: 'e', strand_id: 's',
        is_modification: source === 'chemical-modification-v1', modification: source === 'chemical-modification-v1' ? 'thiol' : null }
      const update = { ...target, placement_source: source, backbone_position: [1, 2, 3],
        base_position: [1, 2, 3], base_normal: [1, 0, 0], axis_tangent: [0, 0, 1], slab_position: null, slab_quaternion: null }
      replaceNativePlacement(target, update)
      expect(target).toEqual(update)
    }
  })

  it('requires genuine slabless identities through full and positions-only decoding', () => {
    const payload = compact(), data = payload.h.FORWARD
    data.pv = ['native-full-extension-v1', 'chemical-modification-v1']
    data.sp = [null, null]; data.sq = [null, null]
    expect(() => expandCompactNucleotides(payload)).toThrow(/Slabless placement is reserved/)
    expect(() => positionUpdateLookup(payload)).toThrow(/Slabless placement is reserved/)
    data.sid = ['s', 's']; data.extid = ['extension', 'modification']
    data.ismod = [false, true]; data.mod = [null, 'thiol']
    const full = expandCompactNucleotides(payload), update = positionUpdateLookup(payload)
    for (let i = 0; i < full.length; i++) expect(full[i]).toMatchObject(update.get(`h:2:FORWARD:${i}`))
    delete data.ismod
    expect(() => expandCompactNucleotides(payload)).toThrow(/Slabless placement is reserved/)
    expect(() => positionUpdateLookup(payload)).toThrow(/Slabless placement is reserved/)
  })
})
