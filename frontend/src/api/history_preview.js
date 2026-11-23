/** Restore committed display state before history deltas use it as their base. */
let cancelPreview = null
let pending = null

export function registerHistoryPreviewCanceller(cancel) {
  cancelPreview = cancel
  return () => { if (cancelPreview === cancel) cancelPreview = null }
}

export async function cancelHistoryPreview() {
  if (pending) return pending
  pending = Promise.resolve().then(() => cancelPreview?.())
  try { return await pending } finally { pending = null }
}
