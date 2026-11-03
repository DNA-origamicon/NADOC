import { registerShortcut } from './shortcuts.js'

// Shared by the 3D viewer and cadnano editor. Auto Crossover and Autobreak
// have no separate hotkeys; Full Autostaple owns key 2.
export function registerWorkflowShortcuts() {
  for (const [key, menuId, description] of [
    ['1', 'menu-routing-scaffold-ends', 'Autoscaffold'],
    ['2', 'menu-routing-full-autostaple', 'Full Autostaple'],
    ['4', 'menu-seq-update-routing', 'Add Loops/Skips'],
    ['5', 'menu-seq-assign-scaffold', 'Scaffold sequence'],
    ['6', 'menu-seq-assign-staples', 'Staple sequence'],
    ['0', 'menu-seq-hairpin-dimer', 'Hairpin/dimer checker'],
  ]) {
    registerShortcut({
      key, ctrl: false, shift: false, alt: false,
      description, blockedInInput: true, noRepeat: true,
      handler(e) {
        e.preventDefault()
        const button = document.getElementById(menuId)
        if (button && !button.disabled) button.click()
      },
    })
  }
}
