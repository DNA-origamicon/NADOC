/**
 * Overhang-orientation right-click context menu.
 *
 * Extracted verbatim from main.js's inline `_showOverhangOrientMenu` /
 * `_dismissOvhgMenu` (ISSUE-1 Phase 2a-orientation — context-menu primitive
 * migration). Behaviour is preserved; the only change is that positioning /
 * outside-click / Escape dismissal now come from the shared `createContextMenu`
 * primitive instead of bespoke `position:fixed` DOM + a hand-rolled pointerdown
 * dismiss listener.
 *
 * The "Representation ▸" entry is a hover-flyout submenu built by
 * `createRepresentationMenuItem` — the primitive can't express a flyout, so it
 * rides in as a `{ type: 'custom', el }` passthrough item. Clicks inside the
 * flyout don't auto-dismiss (it's a DOM child of the menu); the flyout's own
 * option handlers call `dismiss()` before applying.
 *
 * The owning `contextmenu` raycast listener stays in main.js (it routes the
 * right-clicked overhang ids here via `onOverhangRightClick`); this module owns
 * only the menu itself.
 *
 * Items:
 *   Edit Orientation · Reset Orientation
 *   [single overhang]  (sep) Set Label… · Generate OH binding strand
 *   (sep) Representation ▸ (flyout)
 *   (sep) Open Overhangs Manager…
 *   (sep) Clear All Overhangs (danger)
 */

import { createContextMenu } from './primitives/context_menu.js'

/**
 * @param {object} deps
 * @param {object} deps.api                    — patchOverhangRotationsBatch / patchOverhang / generateBinderForOverhang / saveRepresentationOverrides / clearOverhangs
 * @param {{ getState: () => object }} deps.store
 * @param {object} deps.assemblyRenderer        — invalidateInstance / rebuild
 * @param {(ovhgIds?: any[]) => void} deps.openOverhangsManager
 * @param {() => { open: (ovhgIds: any[]) => void }} deps.getOrientPanel  — lazy (panel inits later in main())
 * @param {(design: object, ovhgIds: any[]) => any[]} deps.overhangsToSegments
 * @param {(overrides: any[], segs: any[], rep: string|null) => any[]} deps.editOverridesForSegments
 * @param {(o: { apply: (rep: string|null) => void, dismiss: () => void }) => HTMLElement} deps.createRepresentationMenuItem
 * @returns {{ show: (ovhgIds: any[], x: number, y: number) => void, hide: () => void }}
 */
export function initOverhangOrientationMenu({
  api,
  store,
  assemblyRenderer,
  openOverhangsManager,
  getOrientPanel,
  overhangsToSegments,
  editOverridesForSegments,
  createRepresentationMenuItem,
}) {
  let _menu = null

  function hide() {
    _menu?.close()
    _menu = null
  }

  function show(ovhgIds, clientX, clientY) {
    hide()

    const items = [
      { label: 'Edit Orientation', onClick: () => getOrientPanel().open(ovhgIds) },
      {
        label: 'Reset Orientation',
        onClick: async () => {
          await api.patchOverhangRotationsBatch(ovhgIds.map(id => ({ overhang_id: id, rotation: [0, 0, 0, 1] })))
          if (store.getState().assemblyActive) {
            const { activeInstanceId, currentAssembly } = store.getState()
            if (activeInstanceId) assemblyRenderer.invalidateInstance(activeInstanceId)
            await assemblyRenderer.rebuild(currentAssembly)
          }
        },
      },
    ]

    if (ovhgIds.length === 1) {
      items.push({ type: 'separator' })
      items.push({
        label: 'Set Label…',
        onClick: () => {
          const existing = store.getState().currentDesign?.overhangs?.find(o => o.id === ovhgIds[0])?.label ?? ''
          const name = prompt('Overhang label:', existing)
          if (name === null) return
          api.patchOverhang(ovhgIds[0], { label: name.trim() || null })
        },
      })
      items.push({
        label: 'Generate OH binding strand',
        onClick: async () => {
          try { await api.generateBinderForOverhang(ovhgIds[0]) } catch { /* lastError */ }
        },
      })
    }

    // Representation override for the overhang region(s) — hover flyout submenu.
    items.push({ type: 'separator' })
    items.push({
      type: 'custom',
      el: createRepresentationMenuItem({
        dismiss: hide,
        apply: (rep) => {
          const design = store.getState().currentDesign
          const segs = overhangsToSegments(design, ovhgIds)
          const next = editOverridesForSegments(design?.representation_overrides ?? [], segs, rep)
          api.saveRepresentationOverrides(next)
        },
      }),
    })

    // Always-available entry into the manager — passes whichever overhang(s)
    // were right-clicked through as the prepopulation.
    items.push({ type: 'separator' })
    items.push({
      label: 'Open Overhangs Manager…',
      onClick: () => {
        if (!store.getState().currentDesign?.helices?.length) return
        openOverhangsManager(ovhgIds)
      },
    })

    // Global / bulk action — separated bottom section (ISSUE-1 spec decision 4).
    items.push({ type: 'separator' })
    items.push({ label: 'Clear All Overhangs', danger: true, onClick: () => api.clearOverhangs() })

    _menu = createContextMenu({
      x: clientX,
      y: clientY,
      items,
      onClose: () => { _menu = null },
    })
  }

  return { show, hide }
}
