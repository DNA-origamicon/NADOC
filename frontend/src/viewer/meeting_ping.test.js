import { it, expect, vi } from 'vitest'
import { createMeetingPing } from './meeting_ping.js'
it('unlocks audio through interaction and plays one bounded chime per notification', () => {
  const oscillator = { frequency: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), disconnect: vi.fn() }
  const gain = { gain: { setValueAtTime: vi.fn(), linearRampToValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: vi.fn(), disconnect: vi.fn() }
  const createOscillator = vi.fn(() => oscillator), close = vi.fn(async () => {})
  class Audio { state = 'running'; currentTime = 2; createOscillator = createOscillator; createGain = () => gain; close = close }
  const ping = createMeetingPing({ AudioContext: Audio })
  ping.play(); expect(createOscillator).not.toHaveBeenCalled()
  document.dispatchEvent(new Event('pointerdown')); ping.play()
  expect(createOscillator).toHaveBeenCalledOnce(); expect(oscillator.stop).toHaveBeenCalledWith(2.32)
  ping.dispose(); expect(close).toHaveBeenCalledOnce(); ping.play(); expect(createOscillator).toHaveBeenCalledOnce()
})
