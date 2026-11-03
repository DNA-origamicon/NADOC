import { expect, it, vi, afterEach } from 'vitest'
import { initDeformView } from './deform_view.js'
import { getStraightGeometry } from '../api/client.js'
import { store } from '../state/store.js'
vi.mock('../api/client.js',()=>({getStraightGeometry:vi.fn(async()=>{})}))
vi.mock('../state/store.js',()=>({store:{subscribe:vi.fn(),setState:vi.fn()}}))
afterEach(()=>{vi.clearAllMocks();vi.unstubAllGlobals()})
it('applies the final native pose only after straight geometry is ready without animation frames',async()=>{
 let ready
 getStraightGeometry.mockImplementationOnce(()=>new Promise(resolve=>{ready=resolve}))
 vi.stubGlobal('requestAnimationFrame',()=>{throw Error('Native pose must not await browser frames')})
 const renderer={setAxisShaftMode:vi.fn(),applyDeformLerp:vi.fn()}
 const view=initDeformView(renderer)
 view.deactivate({animate:false})
 expect(view.getT()).toBe(0)
 expect(store.setState).toHaveBeenLastCalledWith({deformVisuActive:false})
 const pending=view.activate({animate:false})
 expect(view.getT()).toBe(0)
 ready();await pending
 expect(view.getT()).toBe(1)
 expect(renderer.setAxisShaftMode).toHaveBeenLastCalledWith('deformed')
 expect(store.setState).toHaveBeenLastCalledWith({deformVisuActive:true})
})
