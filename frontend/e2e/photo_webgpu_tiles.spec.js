import {test,expect} from '@playwright/test'

test.use({launchOptions:{args:['--enable-unsafe-webgpu']}})

// Rendering primitives only: no documents, uploads, jobs or saved downloads.
// Canvases/PNG blobs remain in the browser and die with its context. The standard
// reporter and global teardown remove reports and isolated bridge credentials.
test('WebGPU PNG tiles preserve image orientation and join across both axes',async({page})=>{
  test.setTimeout(180000)
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.route('**/trace-tile-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/trace-tile-check')
  const result=await page.evaluate(async()=>{
    if(!await navigator.gpu?.requestAdapter())throw new Error('WebGPU required for this regression')
    const THREE=await import('/node_modules/three/build/three.module.js')
    const {createPhotoMode}=await import('/src/scene/photo_mode.js')
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,2560/1271,.1,100)
    camera.position.z=10
    const renderer=new THREE.WebGLRenderer({alpha:true});renderer.setSize(320,159)
    document.body.append(renderer.domElement)
    const mode=createPhotoMode({scene,camera,renderer,setRenderFn(){},resetRenderFn(){},setResizeCallback(){},clearResizeCallback(){}})
    const meshes=[]
    try{
      mode.activate();mode.setStudioEnvironment(false);mode.setBackground('solid','#000000')
      mode.setPathTraceSamples(1);mode.setPathTraceExportBackend('webgpu');mode.setPathTracing(true)
      // Different top/bottom colors reveal per-tile inversion. The tall center
      // bar spans the horizontal seam; the red/blue bars span vertical seams.
      const markers=[{color:0xff0000,x:-.36,y:.35,w:.5,h:.16},
        {color:0x0000ff,x:.36,y:-.25,w:.5,h:.16},
        {color:0x00ff00,x:0,y:.08,w:.06,h:1.3}]
      const halfHeight=10*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))
      for(const m of markers){
        const mesh=new THREE.Mesh(new THREE.PlaneGeometry(m.w*halfHeight*camera.aspect,m.h*halfHeight),
          new THREE.MeshStandardMaterial({color:m.color}))
        mesh.position.set(m.x*halfHeight*camera.aspect,m.y*halfHeight,0);scene.add(mesh);meshes.push(mesh)
      }
      mode.resync()
      // Supply emission after Appearance has installed its selected materials.
      for(let i=0;i<meshes.length;i++)meshes[i].material.emissive.set(markers[i].color)
      const outputs=[]
      // Odd dimensions also cover padded GPU rows and clipped edge tiles.
      for(const [width,height] of [[320,159],[2560,1271]]){
        const progress=[]
        const blob=await mode.renderToBlob(width,height,{onProgress:p=>progress.push(p)})
        const bitmap=await createImageBitmap(blob),canvas=Object.assign(document.createElement('canvas'),{width,height})
        const ctx=canvas.getContext('2d');ctx.drawImage(bitmap,0,0);bitmap.close()
        const pixels=ctx.getImageData(0,0,width,height).data
        const sums=Array.from({length:3},()=>({n:0,x:0,y:0,minY:height,maxY:0}))
        for(let y=0;y<height;y++)for(let x=0;x<width;x++){
          const i=4*(y*width+x)
          for(let c=0;c<3;c++)if(pixels[i+c]>80 && pixels[i+c]>pixels[i+(c+1)%3]+50 && pixels[i+c]>pixels[i+(c+2)%3]+50){
            const s=sums[c];s.n++;s.x+=x;s.y+=y;s.minY=Math.min(s.minY,y);s.maxY=Math.max(s.maxY,y)
          }
        }
        outputs.push({width,height,colors:sums.map(s=>({...s,x:s.x/s.n/width,y:s.y/s.n/height,minY:s.minY/height,maxY:s.maxY/height})),
          // Sampling well within the bar should never expose a seam or gap.
          seam:Array.from({length:9},(_,i)=>Array.from(pixels.slice(4*((Math.floor(height/2)-4+i)*width+Math.floor(width/2)),4*((Math.floor(height/2)-4+i)*width+Math.floor(width/2))+4))),
          tiles:Math.max(...progress.filter(p=>p.stage==='tracing').map(p=>p.tiles??0))})
      }
      return outputs
    }finally{mode.deactivate();renderer.dispose();for(const m of meshes){m.geometry.dispose();m.material.dispose()}}
  })
  console.log('WEBGPU_TILE_ORIENTATION',JSON.stringify(result))
  expect(result.map(r=>r.tiles)).toEqual([1,6])
  for(const output of result){
    const [red,green,blue]=output.colors
    expect(red.n).toBeGreaterThan(100);expect(blue.n).toBeGreaterThan(100)
    expect(red.x).toBeCloseTo(.32,2);expect(red.y).toBeCloseTo(.325,2)
    expect(blue.x).toBeCloseTo(.68,2);expect(blue.y).toBeCloseTo(.625,2)
    expect(Math.abs(green.minY-.135)).toBeLessThan(2/output.height)
    expect(Math.abs(green.maxY-.785)).toBeLessThan(2/output.height)
    for(const pixel of output.seam)expect(pixel[1]).toBeGreaterThan(100)
  }
  expect(errors).toEqual([])
})
