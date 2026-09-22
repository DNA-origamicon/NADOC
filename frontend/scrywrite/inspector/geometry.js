// Pure OpenXR LOCAL -> submitted-eye projection; image coordinates are top-down.
export function rotate(q, v) {
  const [x,y,z,w]=q, [a,b,c]=v
  const t=[2*(y*c-z*b),2*(z*a-x*c),2*(x*b-y*a)]
  return [a+w*t[0]+y*t[2]-z*t[1],b+w*t[1]+z*t[0]-x*t[2],c+w*t[2]+x*t[1]-y*t[0]]
}
export function project(point, eye) {
  const q=eye.orientation_xyzw, local=rotate([-q[0],-q[1],-q[2],q[3]],point.map((v,i)=>v-eye.position[i]))
  if (local[2]>=-.001) return null
  const [l,r,u,d]=eye.fov_left_right_up_down.map(Math.tan)
  return [(local[0]/-local[2]-l)/(r-l)*eye.width,(u-local[1]/-local[2])/(u-d)*eye.height]
}
export function corners(target) {
  if (!target.hit_half_right || !target.hit_half_up) return []
  return [[-1,-1],[1,-1],[1,1],[-1,1]].map(([r,u])=>target.position.map((v,i)=>v+r*target.hit_half_right[i]+u*target.hit_half_up[i]))
}
export function targets(state) {
  const controls=(state.controls||[]).map(t=>({...t,key:`${state.menu}:${t.label}`}))
  return [...controls,...(state.extrude?.visible_cells||[]).map(c=>({...c,
    key:`cell:${c.row},${c.column}`,label:`Cell ${c.row}, ${c.column}`,cell:true}))]
}
