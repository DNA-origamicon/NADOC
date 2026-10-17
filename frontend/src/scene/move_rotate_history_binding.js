/** Exclusive ownership of the existing panel; no new control listeners per opening. */
export function createMoveRotateHistoryBinding({ panel, setTransformValues, setJointAngle, showJointMode,
  getJointMode = () => false, onBind = () => {} }) {
  const upgrade = document.createElement('button')
  upgrade.id = 'mr-history-upgrade-btn'; upgrade.type = 'button'; upgrade.hidden = true
  upgrade.textContent = 'Include linked placements'
  upgrade.title = 'Record all placements moved by this feature together, including linked bodies.'
  panel?.append(upgrade)
  const ids = ['mr-current-selection', 'mr-session-hint', 'mr-tx', 'mr-ty', 'mr-tz', 'mr-rx', 'mr-ry', 'mr-rz',
    'mr-ja', 'mr-pivot-sel', 'mr-rotation-section', 'mr-joint-angle-section', 'mr-snap-45', 'mr-frame-sel',
    'mr-apply-btn', 'mr-cancel-btn', 'mr-reset-btn', 'mr-history-upgrade-btn', ...['x', 'y', 'z'].flatMap(a => [`mr-r${a}-dec`, `mr-r${a}-inc`])]
  const nodes = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]))
  const fields = ['mr-tx', 'mr-ty', 'mr-tz', 'mr-rx', 'mr-ry', 'mr-rz', 'mr-ja', 'mr-pivot-sel',
    'mr-snap-45', 'mr-frame-sel', ...['x', 'y', 'z'].flatMap(a => [`mr-r${a}-dec`, `mr-r${a}-inc`])]
  let owner = null
  function status(session) {
    if (owner !== session) return
    const state = session.status, locked = state.expired || state.publicationUnknown || state.refreshNeeded
      || ['prepare', 'apply', 'cancel', 'status', 'refresh'].includes(state.busy)
    const inputsUnavailable = locked || state.inputsUnavailable
    for (const id of fields) if (nodes[id]) nodes[id].disabled = !!inputsUnavailable || session.role !== 'placement'
    upgrade.disabled = !!inputsUnavailable
    if (nodes['mr-reset-btn']) nodes['mr-reset-btn'].disabled = !!inputsUnavailable || session.role === 'reset'
    const apply = nodes['mr-apply-btn']
    if (apply) {
      apply.textContent = state.publicationUnknown ? 'Check saved result' : state.refreshNeeded ? 'Load saved result' : 'Apply'
      apply.disabled = !!state.busy || (!!state.expired && !state.publicationUnknown && !state.refreshNeeded)
    }
    if (nodes['mr-session-hint']) nodes['mr-session-hint'].textContent = state.error?.message
      ?? (state.expired ? 'Preview expired. Reopen the feature to continue.' : session.hint)
  }
  function call(session, name, ...args) {
    if (owner !== session) return
    const failed = error => { if (owner === session) { session.status = { ...session.status, error }; status(session) } }
    try { Promise.resolve(session.callbacks[name]?.(...args)).catch(failed) } catch (error) { failed(error) }
  }
  function input(session) {
    if (session.jointMode) {
      const value = Number(nodes['mr-ja']?.value)
      if (nodes['mr-ja']?.value.trim() && Number.isFinite(value)) call(session, 'onJointAngle', value)
      else { session.status.error = new Error('Enter a finite joint angle.'); status(session) }
      return
    }
    const raw = ['mr-tx', 'mr-ty', 'mr-tz', 'mr-rx', 'mr-ry', 'mr-rz'].map(id => nodes[id]?.value ?? '')
    const values = raw.map(Number)
    if (raw.some(value => !value.trim()) || values.some(value => !Number.isFinite(value))) {
      session.status.error = new Error('Enter finite translation and rotation values.'); status(session); return
    }
    call(session, 'onTransform', values.slice(0, 3), values.slice(3))
  }
  function handle(event) {
    const session = owner
    if (!session) return
    const node = event.target?.closest?.('input,select,button')
    if (!node || !Object.hasOwn(nodes, node.id)) return
    event.stopImmediatePropagation()
    if (event.type === 'keydown') {
      if (event.key === 'Escape') { event.preventDefault(); call(session, 'onCancel') }
      else if (event.key === 'Enter' && node.tagName === 'INPUT') {
        event.preventDefault(); if (!node.disabled) input(session)
      }
      return
    }
    if (node.disabled) { event.preventDefault(); return }
    const id = node.id
    if (event.type === 'click') {
      const action = { 'mr-apply-btn': 'onApply', 'mr-cancel-btn': 'onCancel', 'mr-reset-btn': 'onReset',
        'mr-history-upgrade-btn': 'onUpgrade' }[id]
      if (action) { event.preventDefault(); call(session, action); return }
      const step = /^mr-r([xyz])-(dec|inc)$/.exec(id)
      if (step) call(session, 'onStep', step[1], step[2] === 'dec' ? -45 : 45,
        nodes['mr-frame-sel']?.value === 'local' ? 'local' : 'world')
    } else if (event.type === 'change') {
      if (id === 'mr-pivot-sel') call(session, 'onPivot', node.value)
      else if (id === 'mr-frame-sel') call(session, 'onFrame', node.value === 'local' ? 'local' : 'world')
      else if (id === 'mr-snap-45') call(session, 'onSnap', node.checked ? 45 : null)
      else input(session)
    }
  }
  for (const event of ['click', 'change', 'keydown']) panel?.addEventListener(event, handle, true)
  return {
    active: () => owner !== null,
    guard: fn => (...args) => { if (!owner) return fn(...args) },
    bind(callbacks) {
      if (!panel) throw new Error('Move/Rotate panel is unavailable')
      if (owner) throw new Error('The Move/Rotate panel already has an active history session')
      const priorJointMode = getJointMode()
      onBind()
      const snapshot = Object.values(nodes).filter(Boolean).map(node => ({ node, value: node.value,
        disabled: node.disabled, checked: node.checked, display: node.style.display,
        children: ['SELECT', 'DIV', 'BUTTON'].includes(node.tagName) ? [...node.childNodes] : null }))
      const display = panel.style.display
      const session = { callbacks, status: {}, role: 'placement', hint: '', jointMode: false }
      owner = session; panel.style.display = ''
      return {
        isCurrent: () => owner === session,
        update({ role = session.role, labels, translation, euler, jointAngle, pivots, pivot,
          jointMode = session.jointMode, hint, placement_upgrade } = {}) {
          if (owner !== session) return
          session.role = role; session.jointMode = jointMode
          session.hint = hint ?? (role === 'reset' ? 'Reset the saved pose at this point in history.'
            : 'Editing a historical feature. Targets remain fixed; Apply rebuilds later features.')
          if (labels && nodes['mr-current-selection']) {
            nodes['mr-current-selection'].replaceChildren(...labels.map(label => {
              const child = document.createElement('div'); child.textContent = label; return child
            }))
          }
          if (translation && euler) setTransformValues(...translation, ...euler)
          if (Number.isFinite(jointAngle)) setJointAngle(jointAngle)
          showJointMode(jointMode)
          if (placement_upgrade !== undefined) upgrade.hidden = !placement_upgrade
          const select = nodes['mr-pivot-sel']
          if (pivots && select) {
            const selected = pivot ?? select.value
            select.replaceChildren(...pivots.map(item => new Option(item.label, item.id)))
            if (pivots.some(item => item.id === selected)) select.value = selected
          } else if (pivot && select) select.value = pivot
          status(session)
        },
        setStatus(value) { if (owner === session) { session.status = { ...value }; status(session) } },
        release() {
          if (owner !== session) return
          owner = null
          showJointMode(priorJointMode)
          for (const prior of snapshot) {
            if (prior.children) prior.node.replaceChildren(...prior.children)
            if (prior.value !== undefined) prior.node.value = prior.value
            if (prior.disabled !== undefined) prior.node.disabled = prior.disabled
            if (prior.checked !== undefined) prior.node.checked = prior.checked
            prior.node.style.display = prior.display
          }
          panel.style.display = display
          upgrade.hidden = true
        },
      }
    },
  }
}
