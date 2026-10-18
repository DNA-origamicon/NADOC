import { captureAssemblyJointInputs, sameAssemblyJointInputs } from '../scene/assembly_joint_inputs.js'
import { getDocId } from '../shared/doc_id.js'

/** Keep row controls only when the complete authored snapshot differs solely
 * in live instance representation. The shared snapshot also includes the
 * non-enumerable source version and detects nested, in-place source edits.
 */
export function initAssemblyPanelRows({ eventTarget = globalThis.window, documentId = getDocId } = {}) {
  const controls = new Map()
  let current = null
  const invalidate = () => { current = null; controls.clear() }
  eventTarget?.addEventListener('nadoc:document-reset', invalidate)

  return {
    register(instanceId, control) { controls.set(instanceId, control) },
    /** Returns true when the caller must rebuild the complete panel. */
    update(assembly) {
      const docId = documentId()
      const inputs = captureAssemblyJointInputs(assembly)
      // An unchanged unversioned snapshot may still service selection. Fresh
      // snapshots require source versions; identity never bypasses value checks.
      const sameSnapshot = current?.assembly === assembly
      const reusable = !!current && current.docId === docId
        && (sameSnapshot || (current.inputs.reusable && inputs.reusable))
        && sameAssemblyJointInputs(current.inputs, inputs)
      current = { assembly, docId, inputs }
      if (!reusable) {
        controls.clear()
        return true
      }
      for (const instance of assembly?.instances ?? []) {
        const control = controls.get(instance.id)
        const representation = instance.representation ?? 'full'
        if (control && control.value !== representation) {
          control.value = representation
          // Match a freshly built select for representations absent from this menu.
          if (control.selectedIndex < 0 && control.options.length) control.selectedIndex = 0
        }
      }
      return false
    },
    dispose() {
      invalidate()
      eventTarget?.removeEventListener('nadoc:document-reset', invalidate)
    },
  }
}
