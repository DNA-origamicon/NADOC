import { it, expect, vi } from 'vitest'
import { attachTrajectoryRenderClock, requestTrajectoryFrame, cancelTrajectoryFrame } from './trajectory_render_clock.js'
it('drives callbacks once per headset frame without depending on window RAF', () => {
  const request = vi.spyOn(globalThis, 'requestAnimationFrame')
  const driver = attachTrajectoryRenderClock(), calls = []
  let next
  requestTrajectoryFrame(time => {
    calls.push(time)
    next = requestTrajectoryFrame(time => calls.push(time))
  })
  driver.tick(11); expect(calls).toEqual([11]); expect(request).not.toHaveBeenCalled()
  driver.tick(22); expect(calls).toEqual([11, 22])
  next = requestTrajectoryFrame(() => { throw new Error('cancelled frame ran') })
  cancelTrajectoryFrame(next); driver.tick(33)
  driver.dispose(); request.mockRestore()
})
it('hands pending callbacks back to browser RAF on runtime disposal', () => {
  vi.useFakeTimers()
  const driver = attachTrajectoryRenderClock(), callback = vi.fn()
  requestTrajectoryFrame(callback); driver.dispose()
  vi.advanceTimersByTime(20)
  expect(callback).toHaveBeenCalledOnce()
  vi.useRealTimers()
})
