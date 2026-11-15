import { showChoice } from './primitives/confirm.js'

/** Confirm accepted tethers and explain rejected marks without claiming success. */
export function createFlexibleSegmentActions({ api, showToast, beginOperationTiming, markOperationTiming }) {
  return async function markFlexibleRun(run) {
    const trace = beginOperationTiming('Mark flexible segment', {
      requestPath: '/design/flexible-segment/batch', nMarks: run.length,
    })
    markOperationTiming('run-resolved', undefined, trace)
    showToast(`Marking ${run.length}-base flexible segment…`)
    markOperationTiming('optimistic-confirmation-visible', undefined, trace)
    const result = await api.batchFlexibleSegment({ marks: run }, {
      onError: (_status, detail) => {
        if (detail?.code === 'flexible_connection_requires_distinct_clusters') {
          void showChoice({ title: 'Cannot mark flexible segment', message: detail.message,
            choices: [{ label: 'OK', value: true }] })
        }
      },
    })
    if (result?.design) showToast(`Marked ${run.length}-base flexible segment`)
    return result
  }
}
