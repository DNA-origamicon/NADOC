/** Six flat, watertight QR plates plus a core. Print plates white, relief black. */
import qrcode from 'qrcode-generator'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

export function cubeMesh(edge = 150) {
  const h=edge/2, p=[[-h,-h,-h],[h,-h,-h],[h,h,-h],[-h,h,-h],[-h,-h,h],[h,-h,h],[h,h,h],[-h,h,h]]
  return [[0,3,2,1],[4,5,6,7],[0,1,5,4],[3,7,6,2],[1,2,6,5],[0,4,7,3]].flatMap(f=>[[p[f[0]],p[f[1]],p[f[2]]],[p[f[0]],p[f[2]],p[f[3]]]])
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
  const buffer=Buffer.alloc(84+triangles.length*50);buffer.write('NADOC QR cube; units millimetres');buffer.writeUInt32LE(triangles.length,80)
  triangles.forEach((triangle,i)=>{const [a,b,c]=triangle, u=b.map((v,k)=>v-a[k]),v=c.map((v,k)=>v-a[k]);const cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...cross);const normal=cross.map(v=>v/length);[...normal,...triangle.flat()].forEach((v,k)=>buffer.writeFloatLE(v,84+i*50+k*4))})
  return buffer
}
async function main() {
  const output=process.argv[2]
  if(!output)throw Error('Usage: node frontend/scripts/generate-qr-cube.mjs OUTPUT_DIRECTORY')
  await mkdir(output,{recursive:false})
  await writeFile(resolve(output,'core-150mm.stl'),stl(cubeMesh()))
  const names=['front','back','right','left','top','bottom'],faces=[]
  for(let face=0;face<6;face++) {
    const mesh=plateMesh(face);await writeFile(resolve(output,`face-${face}-${names[face]}.stl`),stl(mesh.triangles));faces.push({face,name:names[face],payload:mesh.data})
  }
  await writeFile(resolve(output,'assembly.json'),JSON.stringify({units:'mm',coreEdge:150,plateWidth:150,plateBase:3,relief:.6,markerPlaneOffset:78.6,faces},null,2)+'\n')
  await writeFile(resolve(output,'README.txt'),'NADOC QR cube — millimetres\nPrint the 150 mm core with ordinary slicer infill. Print all six plates flat, white up to Z=3 mm, black for the final 0.6 mm; alternatively paint only raised modules matte black. The plain core can also receive paper labels.\nCenter each plate on its named core face, base against core. On vertical faces, QR top points toward cube top. On the top face, QR top points toward the BACK face; on the bottom face, QR top points toward FRONT. QR right on top/bottom points toward cube RIGHT. Verify the whole QR square including quiet zone measures 150 mm. Avoid thick adhesive; nominal QR plane is 78.6 mm from cube center.\nThese permanent codes identify cube faces, not a meeting invitation. Use the separate guest QR for scan-to-join. Do not distribute duplicate cubes in the same calibration area. Native calibration maps each face to cube center. Mobile cube registration is not yet implemented. Test decoding after printing; an unpainted single-color relief is not a reliable optical QR.\n')
  console.log(`Wrote seven STL files and assembly instructions to ${resolve(output)}`)
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href)main().catch(e=>{console.error(e.message);process.exitCode=1})
