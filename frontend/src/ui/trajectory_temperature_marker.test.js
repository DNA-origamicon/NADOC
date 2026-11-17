// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { createTrajectoryMarker, trajectoryMarkerLabel } from './trajectory_temperature_marker.js'
import { initOxdnaTrajectoryPlayer, markerPositions } from './oxdna_trajectory_player.js'
import { initFrameRangeSlider } from './frame_range_slider.js'
const marker = { frame: 3, end_frame: 8, temperature_c: 35, kind: 'production', label: '→ production', stage_name: '2_thermal', pct: 30 }
it('describes the following frames as thermostat targets, including cooling below zero', () => {
  expect(trajectoryMarkerLabel(marker)).toContain('35 °C — target temperature from frame 4 through 9')
  expect(trajectoryMarkerLabel({...marker,temperature_c:-5})).toContain('-5 °C')
  expect(trajectoryMarkerLabel({label:'equil',stage_name:'1'})).toBe('equil (1)')
})
it('makes temperature ticks focusable with a hover/focus tooltip', () => {
  const tick=createTrajectoryMarker(marker,'red')
  expect(tick.tabIndex).toBe(0)
  expect(tick.getAttribute('aria-label')).toBe(tick.querySelector('[role=tooltip]').textContent)
  expect(tick.style.left).toBe('30%')
  expect(markerPositions([{...marker,frame:0}],1)[0].pct).toBe(0)
})
it('renders temperatures in both player and animation range scrubber and clears them', () => {
  const markersEl=document.createElement('div')
  const player=initOxdnaTrajectoryPlayer({markersEl})
  player.setTrajectory(10,[marker])
  expect(markersEl.querySelector('[data-temperature-c="35"]')).not.toBeNull()
  const bar=initFrameRangeSlider()
  bar.setFrames(10,[marker])
  expect(bar.el.querySelector('[data-temperature-c="35"]')).not.toBeNull()
  bar.setFrames(10,[]); player.stop()
  expect(bar.el.querySelector('[data-temperature-c]')).toBeNull()
  expect(markersEl.children).toHaveLength(0)
})
