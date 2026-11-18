/** Refit a fixed topology AABB tree; conservative candidates for finite rods.
 * Bounds are rebuilt from the current poses on every query. */
export function createTetherContactIndex(geometry, pairs, reach) {
  const n=geometry.length, lookup=new Int32Array(n*n).fill(-1)
  pairs.forEach(([i,j],k)=>{lookup[i*n+j]=lookup[j*n+i]=k})
  function build(indices) {
    const node={lo:[0,0,0],hi:[0,0,0],count:indices.length}
    if(indices.length<=4)node.indices=indices
    else {
      const spans=[0,1,2].map(c=>Math.max(...indices.map(i=>geometry[i].hi[c]))-Math.min(...indices.map(i=>geometry[i].lo[c])))
      const axis=spans.indexOf(Math.max(...spans))
      indices.sort((a,b)=>geometry[a].lo[axis]+geometry[a].hi[axis]-geometry[b].lo[axis]-geometry[b].hi[axis])
      const mid=indices.length>>1
      node.left=build(indices.slice(0,mid));node.right=build(indices.slice(mid))
    }
    return node
  }
  const root=build(geometry.map((_,i)=>i)), candidates=[]
  function refit(node) {
    node.lo.fill(Infinity);node.hi.fill(-Infinity)
    if(node.indices)for(const i of node.indices)include(node,geometry[i])
    else {refit(node.left);refit(node.right);include(node,node.left);include(node,node.right)}
  }
  function include(a,b){for(let c=0;c<3;c++){a.lo[c]=Math.min(a.lo[c],b.lo[c]);a.hi[c]=Math.max(a.hi[c],b.hi[c])}}
  function separated(a,b){
    let d2=0
    for(let c=0;c<3;c++){const d=Math.max(0,a.lo[c]-b.hi[c],b.lo[c]-a.hi[c]);d2+=d*d}
    return d2>reach*reach
  }
  function visit(a,b){
    if(separated(a,b))return
    if(a===b && !a.indices){visit(a.left,a.left);visit(a.right,a.left);visit(a.right,a.right);return}
    if(a.indices && b.indices){
      for(const i of a.indices)for(const j of b.indices){
        if(a===b && i<=j)continue
        const k=lookup[i*n+j]
        if(k>=0 && !separated(geometry[i],geometry[j]))candidates.push(k)
      }
    } else if(!a.indices && (b.indices || a.count>=b.count)){visit(a.left,b);visit(a.right,b)}
    else {visit(a,b.left);visit(a,b.right)}
  }
  return ()=>{candidates.length=0;refit(root);visit(root,root);return candidates.sort((a,b)=>a-b)}
}
