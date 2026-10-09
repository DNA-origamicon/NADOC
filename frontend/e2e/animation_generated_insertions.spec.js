import { test, expect } from '@playwright/test'
import { readFileSync, writeFileSync, mkdirSync, rmSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const DOC = '__e2e__generated-insertions'
const directory = `${ROOT}workspace/playwright_tests/${DOC}`
const owned = [directory, `${ROOT}workspace/.session/${DOC}`, `${ROOT}workspace/.nadoc-projects/${DOC}`, `${ROOT}workspace/${DOC}.nadoc`]
const evidence = `${ROOT}.development-artifacts/animation-insertion-review`
const API = `${process.env.NADOC_E2E_API_BASE}/api`
// Optional real-document regression. All writes are test-owned; the user's file
// is read only. Retain screenshots as placement-review evidence.
test('generated sweep history animates insertion changes forward and backward', async ({ page, request }) => {
  test.skip(!existsSync(`${ROOT}workspace/4NP_gen_test_aligned.nadoc`), 'Local reproduction document not present')
  test.setTimeout(300000)
  for (const path of owned) expect(existsSync(path)).toBe(false)
  const design = JSON.parse(readFileSync(`${ROOT}workspace/4NP_gen_test_aligned.nadoc`, 'utf8'))
  design.id = DOC; design.metadata.name = DOC
  const sweep = design.feature_log.findIndex(e => e.op_kind === 'sweep')
  const full = process.env.NADOC_ANIMATION_FULL_REVIEW === '1'
  const insertion = design.feature_log.findIndex((e,i) => i > sweep && e.children?.some(c => c.op_subtype === 'loop-skip-insert'))
  const start = full ? sweep - 1 : insertion - 1
  expect(start).toBeGreaterThanOrEqual(0)
  const stop = full ? design.feature_log.length - 1 : start + 1
  design.animations = [{ id:'repro', name:'repro', fps:30, loop:false, keyframes:[
    {id:'a',feature_log_index:start,transition_duration_s:0,hold_duration_s:1,easing:'linear'},
    {id:'b',feature_log_index:stop,transition_duration_s:4,hold_duration_s:1,easing:'linear'},
    {id:'c',feature_log_index:start,transition_duration_s:4,hold_duration_s:1,easing:'linear'},
  ]}]
  mkdirSync(directory,{recursive:true}); mkdirSync(evidence,{recursive:true})
  writeFileSync(`${directory}/${DOC}.nadoc`,JSON.stringify(design))
  try {
    const errors=[];page.on('pageerror',e=>errors.push(e.message))
    await page.goto(`/?doc=${DOC}&open=${encodeURIComponent(`playwright_tests/${DOC}/${DOC}.nadoc`)}`)
    await page.waitForFunction(()=>window.__nadocTest?.store.getState().currentGeometry?.length>0,null,{timeout:90000})
    console.log('Generated insertion document loaded')
    await page.evaluate(async()=>{const t=window.__nadocTest;await t.animPlayer.play(t.store.getState().currentDesign.animations[0]);t.animPlayer.pause()})
    console.log('Generated insertion animation prepared')
    const samples=await page.evaluate(async ({start,stop})=>{
      const t=window.__nadocTest, samples=[]
      for(const offset of [1,6])for(let i=0;i<stop-start;i++){
        const time=offset+4*(i+.5)/(stop-start)
        t.animPlayer.seekTo(time);await t.animPlayer.settleFrame()
        samples.push({time,count:t.getDesignRenderer().getBackboneEntries().length})
      }
      t.animPlayer.seekTo(5);await t.animPlayer.settleFrame()
      return samples
    },{start,stop})
    await page.locator('#canvas').screenshot({path:`${evidence}/full-playback.png`})
    expect(errors).toEqual([])
    expect(await page.getByText('DNA positioning integrity failure',{exact:true}).count()).toBe(0)
    expect(samples.some(s=>s.count>1000)).toBe(true)
    writeFileSync(`${evidence}/playback.json`,JSON.stringify(samples,null,2))
  } finally {
    try { await page.close();await request.delete(`${API}/documents/${DOC}`) }
    finally { for(const path of owned)rmSync(path,{recursive:true,force:true}) }
  }
})
