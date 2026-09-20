/** Full designs and partial authoring responses acknowledge different state.
 * A metadata acknowledgement cannot supersede unapplied topology/geometry.
 * Keep field values until a full snapshot catches up, without cloning geometry.
 */
export function createDesignRevisionTracker() {
  let designRevision = -1, observedRevision = -1
  const fields = new Map()
  const hasRevision = json => Number.isFinite(json?.revision)
  return {
    acceptDesign(json) {
      if (!json?.design || !hasRevision(json)) return true
      if (json.revision < designRevision) return false
      const overlay = {}
      for (const [field, saved] of fields) {
        if (saved.designId !== json.design.id || saved.revision <= json.revision) {
          fields.delete(field)
        } else {
          overlay[field] = saved.value
        }
      }
      if (Object.keys(overlay).length) json.design = { ...json.design, ...overlay }
      designRevision = json.revision
      observedRevision = Math.max(observedRevision, json.revision)
      return true
    },
    acceptMetadata(json, names, designId) {
      if (!hasRevision(json)) return true
      const revision = json.revision
      if (revision < designRevision || names.some(field => {
        const saved = fields.get(field)
        return saved?.designId === designId && revision < saved.revision
      })) return false
      const source = json.design ?? json
      for (const field of names) {
        if (Object.hasOwn(source, field)) {
          fields.set(field, { revision, designId, value: source[field] })
        }
      }
      observedRevision = Math.max(observedRevision, revision)
      return true
    },
    current: () => observedRevision < 0 ? null : observedRevision,
    reset() {
      designRevision = observedRevision = -1
      fields.clear()
    },
  }
}
