import { createPartRepairEndpoints } from '../api/part_repair_endpoints.js'
import { createPartRepairResponse } from '../api/part_repair_response.js'
import { createSourceBoundRequests } from '../api/source_bound_requests.js'
import { createRoutingFeatureAPI } from '../api/routing_feature_endpoints.js'
import { createPatternRequests } from '../api/pattern_requests.js'

/** Same native history transports as 3D; publication targets the editor store. */
export function createFeatureLogAPI({ store, request, syncDesign, revisions, getDocId, headersFor, documentRequests, mutate }) {
  const currentRevision = () => revisions.current()
  const shared = { store, request, syncDesign, getDocId, currentRevision, documentRequests }
  const response = createPartRepairResponse({ store, revisions, getDocId, syncDesign })
  const inputs = createSourceBoundRequests(shared)
  const routing = createRoutingFeatureAPI(shared)
  const patterns = createPatternRequests(shared)
  return {
    summaryPatch: response.summaryPatch,
    partRepairAPI: createPartRepairEndpoints({ request, headersFor, acknowledge: response.acknowledge, apply: response.apply }),
    currentRevisionWatermark: currentRevision,
    captureFeatureEditContext: inputs.capture,
    isFeatureEditContextCurrent: inputs.isCurrent,
    editNativeExtrusionFeature: inputs.edit,
    editFeatureInputs: inputs.edit,
    captureRoutingEditContext: routing.capture,
    isRoutingEditContextCurrent: routing.isCurrent,
    getRoutingFeatureInputs: routing.load,
    editRoutingFeatureInputs: routing.edit,
    capturePatternContext: patterns.capture,
    isPatternContextCurrent: patterns.isCurrent,
    editPatternFeatureInputs: patterns.edit,
    async getFeatureDependencies() {
      const context = inputs.capture()
      const result = await request('GET', '/design/features/dependencies', undefined, { docId: context.docId })
      if (!inputs.isCurrent(context) || result?.design_id !== context.designId || result?.revision !== context.revision)
        throw new Error('The part changed. Reopen the dependency view.')
      return result
    },
    createLoadout: name => mutate(req => req('POST', '/design/loadouts', { name })),
    selectLoadout: (id, { saveCurrent = true } = {}) => mutate(req => req('POST', `/design/loadouts/${encodeURIComponent(id)}/select${saveCurrent ? '' : '?save_current=false'}`)),
    renameLoadout: (id, name) => mutate(req => req('PATCH', `/design/loadouts/${encodeURIComponent(id)}`, { name })),
    deleteLoadout: id => mutate(req => req('DELETE', `/design/loadouts/${encodeURIComponent(id)}`)),
  }
}
