import {it,expect,vi} from 'vitest'
import {pollNativeTrace} from './path_trace_native_progress.js'
it('ignores an earlier frame, reports this frame and aborts pending reads on cleanup',async()=>{
  vi.useFakeTimers()
  const status=vi.fn(),fetcher=vi.fn()
    .mockResolvedValueOnce({ok:true,json:async()=>({request_id:'old',samples:64})})
    .mockResolvedValueOnce({ok:true,json:async()=>({request_id:'new',samples:32})})
    .mockImplementationOnce(()=>new Promise(()=>{}))
  try{
    const stop=pollNativeTrace('session','new',status,{fetcher})
    await vi.advanceTimersByTimeAsync(500);expect(status).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(500);expect(status).toHaveBeenCalledWith({request_id:'new',samples:32})
    await vi.advanceTimersByTimeAsync(500);stop()
    expect(fetcher.mock.calls[2][1].signal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(5000);expect(fetcher).toHaveBeenCalledTimes(3)
  }finally{vi.useRealTimers()}
})
