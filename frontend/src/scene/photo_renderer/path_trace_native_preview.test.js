import {it,expect,vi} from 'vitest'
import {createNativeTracePreviewEngine} from './path_trace_native_preview.js'
const tick=()=>new Promise(r=>setTimeout(r,0))
it('serializes native frames, hides changed scenes and does not claim incomplete samples',async()=>{
  let finish
  const native={samples:0,advance:vi.fn(n=>new Promise(r=>{finish=()=>{native.samples=n;r()}})),update:vi.fn(),reset(){this.samples=0},draw:vi.fn(),dispose:vi.fn()}
  const engine=await createNativeTracePreviewEngine({}, {create:async()=>native})
  engine.advance(64);engine.advance(64);await tick()
  expect(native.advance).toHaveBeenCalledOnce();expect(engine.ready()).toBe(false);expect(engine.samples).toBe(0)
  finish();await tick();expect(engine.samples).toBe(1);engine.draw();expect(native.draw).toHaveBeenCalledOnce()
  engine.advance(64);await tick();expect(native.advance).toHaveBeenLastCalledWith(64,{quick:false})
  const update=engine.update({scene:'new'});engine.draw();expect(engine.samples).toBe(0)
  finish();await update;expect(native.update).toHaveBeenCalledWith({scene:'new'})
  expect(engine.samples).toBe(0);expect(native.draw).toHaveBeenCalledOnce()
  await engine.dispose()
})
it('surfaces async errors through ready and closes without unhandled rejection',async()=>{
  const native={samples:0,advance:async()=>{throw new Error('native device lost')},dispose:vi.fn()}
  const engine=await createNativeTracePreviewEngine({}, {create:async()=>native})
  engine.advance(1);await tick();expect(()=>engine.ready()).toThrow('native device lost')
  await engine.dispose();expect(native.dispose).toHaveBeenCalledOnce()
})
