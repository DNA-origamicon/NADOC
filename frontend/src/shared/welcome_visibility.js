/** The desktop welcome screen is the authority for whether an editor is open. */
export function welcomeVisible(document = globalThis.document) {
  const screen = document?.getElementById('welcome-screen')
  return !!screen && !screen.hidden && !screen.classList.contains('hidden') && screen.style.display !== 'none'
}

export function observeWelcomeVisibility(onChange, document = globalThis.document) {
  const screen = document?.getElementById('welcome-screen')
  if (!screen) return () => {}
  let visible = welcomeVisible(document)
  const observer = new document.defaultView.MutationObserver(() => {
    const next = welcomeVisible(document)
    if (next !== visible) { visible = next; onChange(next) }
  })
  observer.observe(screen, { attributes: true, attributeFilter: ['class', 'hidden', 'style'] })
  return () => observer.disconnect()
}
