/** Bounded transient event, tied to both the scene and its selected target. */
export function validateSelectionPing(value) {
  if (!value || typeof value.revision !== 'string' || !/^[a-f0-9]{64}$/.test(value.revision) ||
      typeof value.target !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(value.target) ||
      !Number.isSafeInteger(value.selectionRevision) || value.selectionRevision < 0 ||
      !value.ping || typeof value.ping.id !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(value.ping.id) ||
      !Number.isSafeInteger(value.ping.createdAt) || value.ping.createdAt < 0 ||
      Object.keys(value).some(k => !['revision', 'target', 'selectionRevision', 'ping'].includes(k)) ||
      Object.keys(value.ping).some(k => !['id', 'createdAt'].includes(k))) throw new Error('Invalid selection ping')
  return { revision: value.revision, target: value.target, selectionRevision: value.selectionRevision, ping: { ...value.ping } }
}
