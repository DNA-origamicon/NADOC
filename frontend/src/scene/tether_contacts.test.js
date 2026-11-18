import { Quaternion, Vector3 } from 'three'
import { describe, it, expect } from 'vitest'
import { duplexGap, buildContactBodies, createTetherContactGuard } from './tether_contacts.js'
const rod = (owner, x, z = 0) => ({ owner, p: [x, 0, z], q: [x, 0, z + 4] })
const pose = x => ({ pos: [x, 0, 0], quat: [0, 0, 0, 1] })
describe('tethered duplex contacts', () => {
  it('uses flat ends and radius one, including degenerate axes', () => {
    expect(duplexGap(rod('a', 0), rod('b', 3))).toBeCloseTo(1)
    expect(duplexGap(rod('a', 0), rod('b', 0, 5))).toBeCloseTo(.666)
    expect(duplexGap(rod('a', 0), rod('b', 1))).toBeCloseTo(-1)
    expect(duplexGap({ p: [0, 0, 0], q: [0, 0, 0] }, rod('b', 3))).toBeCloseTo(1)
  })
  it('retains unowned loose bundles as static obstacles', () => {
    const design = { cluster_transforms: [{ id: 'a', helix_ids: ['a'] }] }
    const geometry = ['a', 'loose'].flatMap(helix_id => [0, 1].map(bp_index => ({ helix_id, bp_index,
      helical_site: { axis_point: [helix_id === 'a' ? 0 : 5, 0, bp_index] } })))
    const bodies = buildContactBodies(design, geometry)
    expect(bodies).toHaveLength(2)
    expect(bodies.some(b => b.owner === 'a')).toBe(true)
    expect(bodies.some(b => b.owner !== 'a')).toBe(true)
  })
  it('blocks crossing an obstacle even with a clear destination and allows disabling', () => {
    const guard = createTetherContactGuard([rod('a', 0), rod('loose', 5)], { a: pose(0) })
    const result = guard.accept({ a: pose(10) })
    expect(result.a.pos[0]).toBeLessThanOrEqual(3.001)
    expect(result.a.pos[0]).toBeGreaterThan(2.8)
    expect(guard.accept({ a: pose(10) }, false).a.pos[0]).toBe(10)
  })
  it('allows escape from an initial overlap but never deepens it', () => {
    const bodies = [rod('a', 0), rod('loose', 1)]
    expect(createTetherContactGuard(bodies, { a: pose(0) }).accept({ a: pose(.5) }).a.pos[0]).toBe(0)
    expect(createTetherContactGuard(bodies, { a: pose(0) }).accept({ a: pose(-3) }).a.pos[0]).toBe(-3)
  })
  it('checks moving links against static and moving bodies', () => {
    const guard = createTetherContactGuard([rod('a', 0), rod('link', 5), rod('fixed', 10)],
      { a: pose(0), link: pose(0) })
    const result = guard.accept({ a: pose(6), link: pose(0) })
    expect(result.a.pos[0]).toBeLessThanOrEqual(3.001)
    expect(result.link.pos).toEqual([0, 0, 0])
  })
  it('does not freeze a move because two fixed bodies overlap', () => {
    const guard = createTetherContactGuard([rod('a', 0), rod('b', 10), rod('c', 10)], { a: pose(0) })
    expect(guard.accept({ a: pose(-2) }).a.pos[0]).toBe(-2)
  })
  it('sweeps rotations even when endpoints finish clear', () => {
    const initial = { a: pose(0) }
    const bodies = [{ owner: 'a', p: [0, 0, 0], q: [8, 0, 0] },
      { owner: 'loose', p: [0, 5, -2], q: [0, 5, 2] }]
    const target = { a: { ...pose(0), quat: new Quaternion().setFromAxisAngle(new Vector3(0, 0, 1), Math.PI).toArray() } }
    const result = createTetherContactGuard(bodies, initial).accept(target)
    expect(new Quaternion(...result.a.quat).angleTo(new Quaternion())).toBeLessThan(Math.PI / 2)
  })
  it('respects exact base ownership and previously previewed poses', () => {
    const broad = { id: 'broad', helix_ids: ['h'], pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1] }
    const exact = { ...broad, id: 'exact', base_ids: [{ helix_id: 'h', bp_index: 1, direction: 'FORWARD' }] }
    const geometry = [0, 1, 2].map(bp_index => ({ helix_id: 'h', bp_index, direction: 'FORWARD', helical_site: { axis_point: [0, 0, bp_index] } }))
    const bodies = buildContactBodies({ cluster_transforms: [broad, exact] }, geometry,
      [{ ...exact, clusterId: 'exact', translation: [10, 0, 0] }])
    expect(bodies.find(b => b.owner === 'exact').p).toEqual([10, 0, 1])
    expect(bodies.filter(b => b.owner === 'broad')).toHaveLength(2)
  })

})

it('preserves contact distance under rigid transforms and swapped endpoints', () => {
  const rotation=new Quaternion().setFromAxisAngle(new Vector3(1,2,3).normalize(),1.2)
  const transform=r=>Object.fromEntries(['p','q'].map(k=>[k,new Vector3(...r[k]).applyQuaternion(rotation).addScalar(31).toArray()]))
  for(let i=0;i<100;i++){
    const a={p:[Math.sin(i)*4,0,1],q:[2,Math.cos(i)*5,7]}
    const b={p:[1,Math.sin(i+1)*3,0],q:[Math.cos(i+2)*4,3,6]}
    const gap=duplexGap(a,b)
    expect(duplexGap(b,a)).toBeCloseTo(gap,9)
    expect(duplexGap({p:a.q,q:a.p},b)).toBeCloseTo(gap,9)
    expect(duplexGap(transform(a),transform(b))).toBeCloseTo(gap,9)
  }
})
