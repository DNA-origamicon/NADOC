// Browser-only review: every backend write blocked; screenshots stay in memory.
const { chromium } = require('../../frontend/node_modules/@playwright/test')
const fs = require('node:fs')
;(async () => {
  const payload=JSON.parse(fs.readFileSync('experiments/strep_biotin_namd/ws/junction_alpine_5ns/extension_review.json','utf8'))
  const browser=await chromium.launch({headless:true})
  try {
    const page=await browser.newPage({viewport:{width:1200,height:850}})
    const errors=[]; page.on('pageerror',e=>errors.push(String(e)))
    await page.route('**/api/**',async route=>{
      const req=route.request()
      if (!['GET','HEAD'].includes(req.method())) return route.fulfill({status:200,contentType:'application/json',body:'{}'})
      return route.continue()
    })
    await page.goto('http://localhost:5173/?doc=__e2e__biotin_browser_only')
    await page.waitForFunction(()=>window._nadocDebug?.selectionManager)
    await page.evaluate(async p=>{
      const {store}=await import('/src/state/store.js')
      store.setState({currentDesign:p.design,currentGeometry:p.geometry,assemblyActive:false})
      document.getElementById('welcome-screen')?.classList.add('hidden')
    },payload)
    await page.waitForFunction(()=>window.__nadocDR.getFluoroEntries().length===1)
    const result=await page.evaluate(async()=>{
      const {store}=await import('/src/state/store.js')
      const d=store.getState().currentDesign
      window._nadocDebug.selectionManager.openExtensionsForStrands(['handle'],300,160)
      return {extensions:d.extensions,rendered:window.__nadocDR.getFluoroEntries().map(e=>({modification:e.nuc.modification,strand_id:e.nuc.strand_id,position:e.pos.toArray()})),domain:d.strands.find(s=>s.id==='handle').domains[0]}
    })
    await page.locator('#__ext-dialog').waitFor()
    result.dialog=await page.locator('#__ext-dialog').innerText()
    result.selectValues=await page.locator('#__ext-dialog select').evaluateAll(es=>es.map(e=>e.value))
    result.errors=errors
    if(result.rendered[0].modification!=='biotin'||!result.selectValues.includes('biotin')||errors.length) throw Error(JSON.stringify(result))
    result.image=(await page.screenshot()).toString('base64')
    process.stdout.write(JSON.stringify(result))
  } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)})
