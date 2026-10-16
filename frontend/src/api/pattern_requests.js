import { createSourceBoundRequests } from './source_bound_requests.js'

/** Bind pattern publication to the document and source shown by the tool. */
export function createPatternRequests(deps) {
  const bound = createSourceBoundRequests({ ...deps, label: 'pattern', requireRevision: false })
  return { capture: bound.capture, isCurrent: bound.isCurrent, edit: bound.edit,
    create(kind, body, context = bound.capture()) {
      if (kind !== 'linear-pattern' && kind !== 'circular-pattern') throw new Error('Unsupported pattern kind.')
      return bound.send(`/design/${kind}`, body, context)
    },
  }
}
