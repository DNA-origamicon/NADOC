/** Printable QR cube geometry shared by the browser export and CLI. */
import qrcode from 'qrcode-generator'

// The QR valley is the white surface of the separately attached top plate.
export function supportSocket(edge = 150, topPlateBase = 3) {
  if (!Number.isFinite(edge) || edge < 20 || edge > 300 ||
      !Number.isFinite(topPlateBase) || topPlateBase < 0 || topPlateBase >= edge * .1) {
    throw Error('Invalid cube dimensions')
  }
  return {
    bottomDiameter: edge * .6,
    topDiameter: edge * .3,
    topClearance: edge * .1,
    depth: edge + topPlateBase - edge * .1,
    topPlateBase,
  }
}
export function cubeMesh(edge = 150, { topPlateBase = 3 } = {}) {
  const socket = supportSocket(edge, topPlateBase)
  const h = edge / 2, ceiling = -h + socket.depth, segments = 128
  const triangles = [], outerBottom = [], outerTop = [], innerBottom = [], innerTop = []
  const quad = (a,b,c,d) => triangles.push([a,b,c], [a,c,d])
  // Rays include all four square corners; shared rings avoid mesh T-junctions.
  for (let i = 0; i < segments; i++) {
    const angle = Math.PI / 4 + i * 2 * Math.PI / segments
    const x = Math.cos(angle), y = Math.sin(angle), scale = h / Math.max(Math.abs(x), Math.abs(y))
    outerBottom.push([x * scale, y * scale, -h])
    outerTop.push([x * scale, y * scale, h])
    innerBottom.push([x * socket.bottomDiameter / 2, y * socket.bottomDiameter / 2, -h])
    innerTop.push([x * socket.topDiameter / 2, y * socket.topDiameter / 2, ceiling])
  }
  for (let i = 0; i < segments; i++) {
    const j = (i + 1) % segments
    quad(outerBottom[i], outerBottom[j], outerTop[j], outerTop[i])
    triangles.push([[0,0,h], outerTop[i], outerTop[j]])
    quad(outerBottom[i], innerBottom[i], innerBottom[j], outerBottom[j])
    // Socket walls and its flat blind end face into the empty cavity.
    quad(innerBottom[i], innerTop[i], innerTop[j], innerBottom[j])
    triangles.push([[0,0,ceiling], innerTop[j], innerTop[i]])
  }
  return triangles
}
export function plateMesh(face, { edge=150, width=150, base=3, relief=.6 } = {}) {
  if (!Number.isInteger(face)||face<0||face>5||![edge,width,base,relief].every(Number.isFinite)||width<20||width>edge||edge>300||base<=0||relief<=0||base+relief>10) throw Error('Invalid cube dimensions')
  const data=`NADOC-CUBE:1:${face}:${edge}:${width}:${base+relief}`
  const qr=qrcode(0,'M');qr.addData(data);qr.make()
  const n=qr.getModuleCount()+8, step=width/n, triangles=[]
  // Tiny white channels keep diagonally touching raised modules manifold.
  const grid=Array.from({length:n},(_,i)=>[i*step,i*step+.04,(i+1)*step-.04]).flat().concat(width), count=n*3
  const occupied=(x,y,z)=>x>=0&&y>=0&&x<count&&y<count&&(z===0||(z===1&&x%3===1&&y%3===1&&x>=12&&y>=12&&x<count-12&&y<count-12&&qr.isDark(n-5-Math.floor(y/3),Math.floor(x/3)-4)))
  const add=p=>triangles.push([p[0],p[1],p[2]],[p[0],p[2],p[3]])
  for(let z=0;z<2;z++)for(let y=0;y<count;y++)for(let x=0;x<count;x++)if(occupied(x,y,z)) {
    const a=grid[x],b=grid[x+1],c=grid[y],d=grid[y+1],e=z?base:0,f=z?base+relief:base
    if(!occupied(x,y,z-1))add([[a,c,e],[a,d,e],[b,d,e],[b,c,e]])
    if(!occupied(x,y,z+1))add([[a,c,f],[b,c,f],[b,d,f],[a,d,f]])
    if(!occupied(x-1,y,z))add([[a,c,e],[a,c,f],[a,d,f],[a,d,e]])
    if(!occupied(x+1,y,z))add([[b,c,e],[b,d,e],[b,d,f],[b,c,f]])
    if(!occupied(x,y-1,z))add([[a,c,e],[b,c,e],[b,c,f],[a,c,f]])
    if(!occupied(x,y+1,z))add([[a,d,e],[a,d,f],[b,d,f],[b,d,e]])
  }
  return { data, triangles, modules: n-8 }
}
export function stl(triangles) {
  const buffer = new Uint8Array(84 + triangles.length * 50), view = new DataView(buffer.buffer)
  buffer.set(new TextEncoder().encode('NADOC QR cube; units millimetres'))
  view.setUint32(80, triangles.length, true)
  triangles.forEach((triangle,i)=>{const [a,b,c]=triangle, u=b.map((v,k)=>v-a[k]),v=c.map((v,k)=>v-a[k]);const cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...cross);const normal=cross.map(v=>v/length);[...normal,...triangle.flat()].forEach((v,k)=>view.setFloat32(84+i*50+k*4,v,true))})
  return buffer
}

export function qrCubeFiles() {
  const files = { 'core-150mm.stl': stl(cubeMesh()) }
  const names=['front','back','right','left','top'],faces=[]
  for(let face=0;face<5;face++) {
    const mesh=plateMesh(face);files[`face-${face}-${names[face]}.stl`] = stl(mesh.triangles);faces.push({face,name:names[face],payload:mesh.data})
  }
  files['assembly.json'] = JSON.stringify({units:'mm',coreEdge:150,plateWidth:150,plateBase:3,relief:.6,markerPlaneOffset:78.6,supportSocket:{axis:"Z",openingZ:-75,...supportSocket()},faces},null,2)+'\n'
  files['README.txt'] = 'NADOC QR cube — millimetres\nPrint the 150 mm core with ordinary slicer infill. The bottom (-Z) has a blind tapered support socket: 90 mm opening diameter, 45 mm end diameter, and 138 mm depth. Its flat end leaves 15 mm to the white surface of the attached top QR plate (12 mm core plus 3 mm plate). Leave the bottom uncovered for a stand, stick, or rod. Print all five plates flat, white up to Z=3 mm, black for the final 0.6 mm; alternatively paint only raised modules matte black. If using paper labels instead of the 3 mm top plate, regenerate cubeMesh with topPlateBase: 0 to preserve the 15 mm top clearance.\nCenter each plate on its named core face, base against core. Alternatively, arrange the five plates in any order and quarter-turn orientation on the five closed faces, then use VR > Calibrate cube in the headset. Keep the cube fixed on its stand while scanning all five faces: red needs scanning, green is accepted, gray is the unmarked support face. The learned arrangement is saved locally and used by Share > Calibrate QR code. On vertical faces, QR top points toward cube top. On the top face, QR top points toward the BACK face. QR right on top points toward cube RIGHT. Verify the whole QR square including quiet zone measures 150 mm. Avoid thick adhesive; nominal QR plane is 78.6 mm from cube center.\nThese permanent codes identify cube faces, not a meeting invitation. Use the separate guest QR for scan-to-join. Do not distribute duplicate cubes in the same calibration area. Native calibration maps each face to cube center. Mobile cube registration is not yet implemented. Test decoding after printing; an unpainted single-color relief is not a reliable optical QR.\n'
  return files
}
