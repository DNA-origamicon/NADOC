/** Measure expanded labels even while the compact presentation clips them. */
export function initEngineTabLayout(mount) {
  let disposed = false
  function refresh() {
    if (disposed) return
    const width = mount.getBoundingClientRect().width
    if (!width) return // A hidden sidebar is measured when it opens.
    const style = getComputedStyle(mount)
    const buttons = [...mount.querySelectorAll('.engine-selector-btn')]
    // Use expanded-mode padding + shoulder clearance (16px), independent of
    // the current compact styling, so the threshold cannot oscillate.
    const widths = buttons.map(button => {
      const children = [...button.children].filter(child => !child.hidden)
      return children.reduce((sum, child) => {
        const childStyle = getComputedStyle(child)
        let contentWidth = child.scrollWidth
        if (child.classList.contains('engine-selector-label')) {
          // A faded label fills its slot; measure the text itself so widening
          // the rail cannot inflate the threshold and trap it in compact mode.
          const range = document.createRange()
          range.selectNodeContents(child)
          contentWidth = range.getBoundingClientRect?.().width ?? contentWidth
        }
        return sum + contentWidth + (parseFloat(childStyle.marginLeft) || 0)
          + (parseFloat(childStyle.marginRight) || 0)
      }, 0) + 16
    })
    // Expanded tabs share equal widths. Reserve room for every label and badge.
    const required = Math.max(0, ...widths) * buttons.length
      + (parseFloat(style.columnGap) || 0) * Math.max(0, buttons.length - 1)
      + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight)
    mount.classList.toggle('is-compact', width < required)
  }
  const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(refresh)
  resize?.observe(mount)
  const mutations = new MutationObserver(refresh)
  mutations.observe(mount, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] })
  document.fonts?.ready.then(refresh)
  refresh()
  return { refresh, dispose() { disposed = true; resize?.disconnect(); mutations.disconnect() } }
}
