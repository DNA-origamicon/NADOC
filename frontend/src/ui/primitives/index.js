/**
 * UI primitives barrel — single import point for all factories.
 *
 *   import { createModal, createButton, createContextMenu, icon, inflateIcons } from './primitives/index.js'
 */

export { el, toggleClass, detach } from './dom.js'
export { createButton } from './button.js'
export { createInput, createSelect } from './input.js'
export { createModal } from './modal.js'
export { createContextMenu } from './context_menu.js'
export { createPanelSection } from './panel_section.js'
export {
  icon,
  inflateIcons,
  observeIcons,
  registerIcon,
  listIcons,
  UNICODE_TO_ICON,
} from './icon.js'
