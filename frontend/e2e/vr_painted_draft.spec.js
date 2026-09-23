import { test, expect } from '@playwright/test'
import fs from 'node:fs'

// Isolated smoke servers disable session cache. This test never creates/saves a
// part or starts VR. Its only persistent output is Playwright's configured report.
// Optional input is a native event captured outside the editable VR workspace.
test('browser preserves native painted cells while authoring frame remains unresolved', async ({ page }) => {
  const event = process.env.NADOC_VR_DRAFT_EVENT
    ? JSON.parse(fs.readFileSync(process.env.NADOC_VR_DRAFT_EVENT, 'utf8'))
    : { tool_config_sequence: 1, tool_config: {
      mode: 'extrude', target_identity: null, target_kind: 'none', target_owner_tokens: [],
      length_bp: 0, direction_sign: 1, strand_filter: 'both', ligate_adjacent: true,
      footprint_state: 'unresolved', extrude_from: 'XY',
      painted_footprint: { lattice_type: 'HONEYCOMB', cells: [[0, 0]] },
    } }
  await page.goto('/?doc=__e2e__vr-painted-draft')
  await expect(page.locator('#canvas')).toBeVisible()
  const result = await page.evaluate(async event => {
    const { initialVRToolConfigState, reduceVRToolConfig } = await import('/src/scene/vr_tool_config.js')
    return reduceVRToolConfig(initialVRToolConfigState,
      { sequence: event.tool_config_sequence, draft: event.tool_config },
      { targetSnapshotPresent: true, toolTarget: null })
  }, event)
  expect(result.accepted).toBe(true)
  expect(result.reason).toBe('incomplete')
  expect(result.state.draft.painted_footprint).toEqual({ lattice_type: 'HONEYCOMB', cells: [[0, 0]] })
  expect(result.state.draft.extrude_from).toBe('XY')
  expect(result.state.draft.footprint_state).toBe('unresolved')
})
