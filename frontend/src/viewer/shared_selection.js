import { mountSelectionPing } from './selection_ping.js'

export function validateSharedSelection(value, root) {
  if (value == null) return
  const fail = () => { throw new Error('Invalid presenter selection') }
  if (typeof value.label !== 'string' || value.label.length > 500 || !Number.isSafeInteger(value.revision) || value.revision < 0 || typeof value.target !== 'string' ||
      Object.keys(value).some(k => !['label', 'revision', 'target', 'ping'].includes(k))) fail()
  let target
  const visit = node => { if (node.uuid === value.target) target = node; node.children.forEach(visit) }; visit(root)
  if (target?.type !== 'Points') fail()
  if (value.ping != null && (typeof value.ping.id !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(value.ping.id) || !Number.isSafeInteger(value.ping.createdAt) || value.ping.createdAt < 0 || Object.keys(value.ping).some(k => !['id', 'createdAt'].includes(k)))) fail()
}

export function mountSharedSelection({ container, runtime }) {
  const label = container.ownerDocument.createElement('div'); label.className = 'shared-selection-label'; label.hidden = true; label.setAttribute('role', 'status'); container.append(label)
  let target = null, identity = null
  const effect = mountSelectionPing({ container, getCamera: () => runtime.camera, getTarget: () => target })
  runtime.addFrameCallback?.(effect.update)
  return { update(current) {
    const selection = current?.data.view?.selection
    const nextIdentity = selection ? `${selection.target}:${selection.revision}` : null
    if (nextIdentity !== identity) effect.clear()
    identity = nextIdentity; target = selection ? current.scene.getObjectByProperty('uuid', selection.target) : null
    label.hidden = !selection; label.textContent = selection ? `Presenter selected: ${selection.label}` : ''
    effect.play(selection?.ping)
  }, dispose() { runtime.removeFrameCallback?.(effect.update); effect.dispose(); label.remove() } }
}
