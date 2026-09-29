import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cubeMesh, plateMesh, stl } from './generate-qr-cube.mjs'
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
  for(let face=0;face<6;face++){const mesh=plateMesh(face);checkClosed(mesh.triangles);codes.add(mesh.data);assert.equal(stl(mesh.triangles).readUInt32LE(80),mesh.triangles.length)}
  assert.equal(codes.size,6)
})
