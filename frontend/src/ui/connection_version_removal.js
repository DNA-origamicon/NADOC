/** Private rollout: native removal and its backend gate must be qualified together. */
export function nativeConnectionRemovalEnabled() { return false }

export function createConnectionVersionRemoval({ enabled, disconnect, patchVersion, deleteVersion,
  connections, bindings, deleteConnection, deleteBinding }) {
  const samePair = (record, version) =>
    (record.overhang_a_id === version.overhang_a_id && record.overhang_b_id === version.overhang_b_id) ||
    (record.overhang_a_id === version.overhang_b_id && record.overhang_b_id === version.overhang_a_id)

  async function legacyTeardown(version) {
    const connection = connections().find(item => samePair(item, version))
    if (connection) await deleteConnection(connection.id)
    const binding = bindings().find(item => samePair(item, version))
    if (binding) await deleteBinding(binding.id)
  }

  return {
    async unapply(version) {
      if (enabled()) return disconnect(version.id, { deleteVersion: false })
      await legacyTeardown(version)
      return patchVersion(version.id, { applied: false })
    },
    async remove(version) {
      if (enabled() && version.applied) return disconnect(version.id, { deleteVersion: true })
      if (version.applied) await legacyTeardown(version)
      return deleteVersion(version.id)
    },
  }
}
