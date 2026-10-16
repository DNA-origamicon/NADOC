import { afterEach, expect, it, vi } from 'vitest'
const f = vi.hoisted(() => ({ history: { open: vi.fn(), active: vi.fn(() => false), onToolExit: vi.fn(), dispose: vi.fn() },
  create: vi.fn(), deleteDeformation: vi.fn(), seekFeatures: vi.fn(), start: vi.fn(), listeners: new Set() }))
vi.mock('./deformation_history_editor.js', () => ({ createDeformationHistoryEditor: (...args) => { f.create(...args); return f.history } }))
vi.mock('../api/client.js', () => ({ deleteDeformation: f.deleteDeformation, seekFeatures: f.seekFeatures }))
vi.mock('../state/store.js', () => ({ store: { getState: () => ({ currentDesign: { id: 'part', feature_log: [] } }),
  subscribe: callback => { f.listeners.add(callback); return () => f.listeners.delete(callback) }, setState: vi.fn() } }))
vi.mock('../scene/deformation_editor.js', () => ({ initDeformationEditor: vi.fn(), previewDeformation: vi.fn(), confirmDeformation: vi.fn(),
  waitForDeformationIdle: vi.fn(), discardDeformationPreview: vi.fn(), exitTool: vi.fn(), getPlanes: () => ({}), repositionPlane: vi.fn(),
  getState: () => 'IDLE', getToolType: () => null, startToolForEdit: f.start, markEditCommitted: vi.fn(),
  startToolForHistory: vi.fn(), finishHistoryTool: vi.fn(), STATES: { IDLE: 'IDLE' } }))
vi.mock('../ui/bend_twist_popup.js', () => ({ showPickingPopup: vi.fn(), initBendTwistPopup: vi.fn(), openPopup: vi.fn(), closePopup: vi.fn(),
  setPlanePositions: vi.fn(), setHistoryPopupStatus: vi.fn() }))
import { initFeatureEditor } from './feature_editor.js'
afterEach(() => vi.clearAllMocks())

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
