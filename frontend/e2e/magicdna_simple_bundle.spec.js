import { test, expect } from '@playwright/test'
import { existsSync, rmSync, readFileSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const API = `${process.env.NADOC_E2E_API_BASE}/api`
// Persistence inventory: guard-published exact copies in __e2e__ scratch; opening
// may autosave loadout UI state. Original shared parts are never opened directly.
// Session cache is disabled by playwright.config.js. Only isolated __e2e__ document
// state and optional review screenshots are created; teardown removes state on
// failure too. Screenshots are temporary review evidence, removed after inspection.
for (const [name, helices, strands] of [['6hb',6,15],['3x6',18,42]]) {
  test(`MagicDNA returned ${name} opens with geometry and process`, async ({page,request}) => {
    test.setTimeout(120000)
    const doc=`__e2e__magicdna-${name}`
    const input=`${ROOT}workspace/Shared Designs/MagicDNA/simple-bundles-v1/${name}-returned.nadoc`
    const designId=JSON.parse(readFileSync(input,'utf8')).id
    const directory=`${ROOT}workspace/playwright_tests/${doc}`
    const owned=[directory,`${ROOT}workspace/.nadoc-projects/${designId}`, `${ROOT}workspace/.session/${doc}`,`${ROOT}workspace/.nadoc-projects/${doc}`,`${ROOT}workspace/${doc}.nadoc`]
    for(const p of owned) expect(existsSync(p)).toBe(false)
    const original=readFileSync(input)
    try {
    mkdirSync(directory,{recursive:true})
    execFileSync(`${ROOT}.venv/bin/python`,['-c','from pathlib import Path; import sys; from backend.core.models import Design; from scripts.agent_structure_guard import publish; publish(Design.model_validate_json(Path(sys.argv[1]).read_bytes()),sys.argv[2])',input,`${directory}/${doc}.nadoc`],{cwd:ROOT})
    const errors=[];page.on('pageerror',e=>errors.push(e.message))
      await page.setViewportSize({width:1400,height:900})
      await page.goto(`/?doc=${doc}&open=${encodeURIComponent(`playwright_tests/${doc}/${doc}.nadoc`)}`)
      await page.waitForFunction(()=>window.__nadocTest?.store.getState().currentGeometry?.length>0,null,{timeout:60000})
      const state=await page.evaluate(()=>{const s=window.__nadocTest.store.getState();return {helices:s.currentDesign.helices.length,strands:s.currentDesign.strands.length,history:s.currentDesign.feature_log.length}})
      expect(state.helices).toBe(helices);expect(state.strands).toBe(strands);expect(state.history).toBeGreaterThan(0)
      await page.waitForTimeout(1000)
      if(process.env.MAGICDNA_REVIEW_SCREENSHOTS==='1') await page.screenshot({path:`${ROOT}.development-artifacts/magicdna-converter/${name}-nadoc.png`})
      expect(errors).toEqual([])
    } finally {
      try { await page.close();await request.delete(`${API}/documents/${doc}`) }
      finally { for(const p of owned) {rmSync(p,{recursive:true,force:true});expect(existsSync(p)).toBe(false)} }
      expect(readFileSync(input).equals(original)).toBe(true)
    }
  })
}
