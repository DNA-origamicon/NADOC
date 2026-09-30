import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cubeMesh, plateMesh, stl, supportSocket } from './generate-qr-cube.mjs'
function checkClosed(triangles) {
  const edges=new Map()
  for(const t of triangles)for(let i=0;i<3;i++) {
    const a=t[i].map(v=>v.toFixed(5)).join(','),b=t[(i+1)%3].map(v=>v.toFixed(5)).join(',')
    const key=[a,b].sort().join('|');edges.set(key,(edges.get(key)||0)+1)
  }
  assert.ok([...edges.values()].every(n=>n===2),'every mesh edge belongs to two triangles')
  let volume=0
  for(const [a,b,c] of triangles)volume+=a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0])
  assert.ok(volume>0,'outward winding and positive volume')
}
test('core and six unique QR plates are closed printable meshes',()=>{
  checkClosed(cubeMesh());const codes=new Set()
  for(let face=0;face<6;face++){const mesh=plateMesh(face);checkClosed(mesh.triangles);codes.add(mesh.data);assert.equal(new DataView(stl(mesh.triangles).buffer).getUint32(80, true),mesh.triangles.length)}
  assert.equal(codes.size,6)
})

function signedVolume(triangles) {
  return triangles.reduce((sum, [a,b,c]) => sum + (
    a[0]*(b[1]*c[2]-b[2]*c[1]) + a[1]*(b[2]*c[0]-b[0]*c[2]) + a[2]*(b[0]*c[1]-b[1]*c[0])
  ) / 6, 0)
}

test('support socket scales, opens at the bottom, and leaves clearance below the QR valley', () => {
  for (const edge of [50, 150, 300]) for (const topPlateBase of [0, 3]) {
    const mesh = cubeMesh(edge, { topPlateBase }), socket = supportSocket(edge, topPlateBase)
    checkClosed(mesh)
    const h = edge / 2, ceiling = h + topPlateBase - edge * .1
    const points = mesh.flat(), near = (a,b) => Math.abs(a-b) < 1e-8
    for (const [z, radius] of [[-h, edge*.3], [ceiling, edge*.15]]) {
      const ring = points.filter(p => near(p[2],z) && near(Math.hypot(p[0],p[1]),radius))
      assert.equal(new Set(ring.map(p => p.join(','))).size, 128)
    }
    assert.ok(near(h + topPlateBase - ceiling, edge*.1))
    // Exact volume of the polygonal frustum: catches a filled opening, wrong
    // depth/radii, inverted inner walls, or an accidentally through-going bore.
    const r = edge*.3, t = edge*.15
    const removedVolume = 128/2*Math.sin(2*Math.PI/128)*socket.depth/3*(r*r+r*t+t*t)
    assert.ok(near(signedVolume(mesh) / (edge**3 - removedVolume), 1))
    const bottom = mesh.filter(tri => tri.every(p => near(p[2], -h)))
    assert.ok(bottom.length > 0)
    assert.ok(bottom.flat().every(p => Math.hypot(p[0],p[1]) >= r - 1e-8))
    const cap = mesh.filter(tri => tri.every(p => near(p[2], ceiling)))
    assert.equal(cap.length, 128)
    assert.ok(cap.flat().every(p => Math.hypot(p[0],p[1]) <= t + 1e-8))
  }
})
