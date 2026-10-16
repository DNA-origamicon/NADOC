import { afterEach, expect, it, vi } from 'vitest'
const f = vi.hoisted(() => ({ history: { open: vi.fn(), active: vi.fn(() => false), onToolExit: vi.fn(), dispose: vi.fn() },
  create: vi.fn(), deleteDeformation: vi.fn(), seekFeatures: vi.fn(), start: vi.fn(), scope: vi.fn(), listeners: new Set() }))
vi.mock('./deformation_history_editor.js', () => ({ createDeformationHistoryEditor: (...args) => { f.create(...args); return f.history } }))
vi.mock('../api/client.js', () => ({ deleteDeformation: f.deleteDeformation, seekFeatures: f.seekFeatures }))
vi.mock('../state/store.js', () => ({ store: { getState: () => ({ currentDesign: f.design ?? { id: 'part', feature_log: [] } }),
  subscribe: callback => { f.listeners.add(callback); return () => f.listeners.delete(callback) }, setState: vi.fn() } }))
vi.mock('../scene/deformation_editor.js', () => ({ initDeformationEditor: vi.fn(), previewDeformation: vi.fn(), confirmDeformation: vi.fn(),
  waitForDeformationIdle: vi.fn(), discardDeformationPreview: vi.fn(), exitTool: vi.fn(), getPlanes: () => ({}), repositionPlane: vi.fn(),
  getState: () => 'IDLE', getToolType: () => null, startToolForEdit: f.start, markEditCommitted: vi.fn(),
  startToolForHistory: vi.fn(), finishHistoryTool: vi.fn(), updateHistoryScope: f.scope, STATES: { IDLE: 'IDLE' } }))
vi.mock('../ui/bend_twist_popup.js', () => ({ showPickingPopup: vi.fn(), initBendTwistPopup: vi.fn(), openPopup: vi.fn(), closePopup: vi.fn(),
  setPlanePositions: vi.fn(), setHistoryPopupStatus: vi.fn() }))
import { initFeatureEditor } from './feature_editor.js'
afterEach(() => { f.design = null; vi.clearAllMocks() })

it('does not seek or open the old mutating placement history editor for separate groups', async () => {
  f.design = { id: 'part', group_organization: { version: 1, groups: [] }, feature_log: [] }
  const showToast = vi.fn(), activateTranslateRotateTool = vi.fn()
  const owner = initFeatureEditor({ showToast, activateTranslateRotateTool })
  await owner.onEditFeature({ feature_type: 'cluster_op', cluster_id: 'same' }, 0)
  expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/isolated history/), 5000)
  expect(f.seekFeatures).not.toHaveBeenCalled()
  expect(activateTranslateRotateTool).not.toHaveBeenCalled()
  owner.dispose()
})

it('qualified history dispatch uses the stable private editor and never peels or seeks on refusal', async () => {
  f.history.open.mockResolvedValue(false)
  const owner = initFeatureEditor({ isolatedHistoryEnabled: true, showToast: vi.fn() })
  const entry = { id: 'feature', feature_type: 'deformation', op_snapshot: { id: 'bend', type: 'bend' } }
  await owner.onEditFeature(entry, 3)
  expect(f.history.open).toHaveBeenCalledWith(entry, 3)
  expect(f.deleteDeformation).not.toHaveBeenCalled(); expect(f.seekFeatures).not.toHaveBeenCalled(); expect(f.start).not.toHaveBeenCalled()
  owner.dispose(); expect(f.listeners.size).toBe(0)
})

it('keeps ordinary rollout gated pending desktop and latency qualification', () => {
  const owner = initFeatureEditor({ showToast: vi.fn() })
  expect(f.create).not.toHaveBeenCalled()
  owner.dispose(); expect(f.listeners.size).toBe(0)
})


it('wires server-selected private guide scope without a canonical update path', () => {
  const owner = initFeatureEditor({ isolatedHistoryEnabled: true, showToast: vi.fn() })
  const scope = { id: 'bend', affected_helix_ids: ['h'], target_ranges: null }
  f.create.mock.lastCall[0].editor.updateHistoryScope(scope)
  expect(f.scope).toHaveBeenCalledWith(scope)
  expect(f.deleteDeformation).not.toHaveBeenCalled(); expect(f.seekFeatures).not.toHaveBeenCalled()
  owner.dispose(); expect(f.listeners.size).toBe(0)
})
