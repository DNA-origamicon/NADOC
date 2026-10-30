import { test, expect } from '@playwright/test'
import { writeFileSync } from 'node:fs'

test('exported grid keeps its apparent line weight at 4x resolution', async ({ page }) => {
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/grid-export-test', r => r.fulfill({ contentType:'text/html', body:'<html><body></body></html>' }))
  await page.goto('/grid-export-test')
  const result = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { createPhotoMode } = await import('/src/scene/photo_mode.js')
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45,4/3,.1,100)
    camera.position.set(0,8,10); camera.lookAt(0,0,0)
    const grid = new THREE.GridHelper(12,12,0xffffff,0xffffff)
    scene.add(grid)
    const renderer = new THREE.WebGLRenderer({antialias:true})
    renderer.setSize(640,480)
    const mode = createPhotoMode({scene,camera,renderer,setRenderFn(){},resetRenderFn(){},setResizeCallback(){},clearResizeCallback(){}})
    mode.activate(); mode.setBackground('solid','#000000')
    async function capture(scale) {
      const bitmap = await createImageBitmap(await mode.renderToBlob(640*scale,480*scale))
      const canvas = document.createElement('canvas');canvas.width=640;canvas.height=480
      const ctx = canvas.getContext('2d');ctx.drawImage(bitmap,0,0,640,480);bitmap.close()
      const data = ctx.getImageData(0,0,640,480).data
      let weight=0
      for(let i=0;i<data.length;i+=4) weight+=data[i]
      return {weight,url:canvas.toDataURL()}
    }
    const normal=await capture(1), high=await capture(4)
    const restored=grid.visible && !scene.getObjectByName('photoExportGrid')
    grid.visible=false
    const off=await capture(1)
    mode.deactivate(); renderer.dispose();grid.geometry.dispose();grid.material.dispose()
    return {normal,high,off:off.weight,restored}
  })
  if(process.env.NADOC_E2E_SHOT) for(const key of ['normal','high'])
    writeFileSync(process.env.NADOC_E2E_SHOT.replace('.png',`-${key}.png`),Buffer.from(result[key].url.split(',')[1],'base64'))
  expect(errors).toEqual([])
  expect(result.normal.weight).toBeGreaterThan(10000)
  expect(result.high.weight/result.normal.weight).toBeGreaterThan(.85)
  expect(result.high.weight/result.normal.weight).toBeLessThan(1.15)
  expect(result.off).toBe(0)
  expect(result.restored).toBe(true)
})
