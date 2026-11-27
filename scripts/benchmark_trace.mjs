#!/usr/bin/env node
// Run with native Windows node.exe for the workstation ANGLE/D3D GPU, or local
// node for other platforms. Never drives an existing browser/user document.
// Only Playwright's temporary profile/download directory is persisted; browser
// close removes it in finally, including errors/timeouts. No reports. Optional
// NADOC_BENCH_CAPTURE writes two images under a caller-owned temporary prefix;
// the caller must remove them after review. Forward it and NADOC_BENCH_DENOISE
// through WSLENV when invoking Windows Node from WSL.
import {writeFile} from 'node:fs/promises'
import {chromium} from '../frontend/node_modules/playwright/index.mjs'
const args=process.argv.slice(2),url=args[0]??'http://localhost:5173',width=Number(args[1]??1280),height=Number(args[2]??720),instances=Number(args[3]??0),samples=Number(args[4]??128)
// Optional A/B tree override; forward NADOC_BENCH_BVH through WSLENV from WSL.
const denoise=process.env.NADOC_BENCH_DENOISE!=='0',capture=process.env.NADOC_BENCH_CAPTURE
const bvhOptions=process.env.NADOC_BENCH_BVH?JSON.parse(process.env.NADOC_BENCH_BVH):undefined
const executablePath=process.env.NADOC_BENCH_BROWSER??(process.platform==='win32'?'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe':undefined)
let browser
const watchdog=setTimeout(()=>{void browser?.close()},240000);watchdog.unref()
try{
  browser=await chromium.launch({executablePath,headless:true,args:['--disable-background-timer-throttling'],timeout:30000})
  const page=await browser.newPage({viewport:{width,height}}),errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.route('**/trace-benchmark-check',r=>r.fulfill({contentType:'text/html',body:'<html><body style="margin:0"></body></html>'}))
  await page.goto(`${url}/trace-benchmark-check`)
  const result=await page.evaluate(async({width,height,instances,samples,bvhOptions,denoise,capture})=>{
    const {runTraceBenchmark}=await import('/e2e/helpers/trace_benchmark_fixture.js')
    return runTraceBenchmark({width,height,instances,samples,bvhOptions,denoise,capture})
  },{width,height,instances,samples,bvhOptions,denoise,capture})
  for(const [name,data] of Object.entries(result.captures??{}))await writeFile(`${capture}-${name}.png`,Buffer.from(data.split(',')[1],'base64'))
  delete result.captures
  if(errors.length)throw new Error(errors.join('\n'))
  if(/swiftshader|llvmpipe|software/i.test(result.adapter))throw new Error(`Hardware benchmark refused software renderer: ${result.adapter}`)
  console.log(JSON.stringify(result))
}finally{clearTimeout(watchdog);await browser?.close()}
