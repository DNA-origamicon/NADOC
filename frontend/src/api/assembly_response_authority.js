// Response provenance belongs to the accepted snapshot, never to a local clone
// that may carry optimistic display values. Weak keys do not retain documents.
const representations = new WeakMap()
const revisions = new WeakMap()

export function recordAssemblyResponse(assembly, response) {
  if (Number.isInteger(response?.revision)) revisions.set(assembly, response.revision)
  const rows = (assembly.instances ?? []).map(row => [row.id, row.representation])
  representations.set(assembly, rows)
  if (response) representations.set(response, rows)
}

export function confirmedAssemblyRevision(assembly) {
  return assembly && revisions.get(assembly)
}

/** A private copy also protects the recorded values from in-place UI edits. */
export function confirmedAssemblyRepresentations(snapshotOrResponse) {
  const rows = snapshotOrResponse && representations.get(snapshotOrResponse)
  return rows ? new Map(rows) : null
}
