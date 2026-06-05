// Background settings modal — View menu → "Background Settings…".
//
// Lets the user set the viewport background to a solid colour, a tiled image,
// or the built-in "aqueous/underwater" gradient theme. The modal markup lives
// in index.html (`#background-modal-body`); this factory wires its inputs,
// owns the `_backgroundState`, applies the chosen style to the viewport
// container, and lazily builds the createModal shell on first open.
//
// Extracted verbatim from main.js (banner `// ── Coloring submenu` tail — the
// Background block). Fully self-contained: no store/scene/camera/designRenderer
// — only DOM + the shared `createModal`/`createButton` primitives. The pure
// style-resolution core is `computeBackgroundStyle`.

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'

// The "aqueous/underwater" theme gradient (was `_formatAqueousBackground`).
const AQUEOUS_GRADIENT =
  `radial-gradient(circle at 18% 18%, rgba(255,255,255,0.18), transparent 5%),
      radial-gradient(circle at 78% 22%, rgba(255,255,255,0.14), transparent 4%),
      radial-gradient(circle at 35% 72%, rgba(255,255,255,0.16), transparent 5%),
      radial-gradient(circle at 65% 80%, rgba(255,255,255,0.12), transparent 6%),
      linear-gradient(180deg, rgba(21,96,143,0.94), rgba(2,40,66,0.96))`

/**
 * Pure: resolve a background `state` to the CSS properties to apply and the
 * preview-label text. `backgroundSize` is `null` in solid-colour mode (the
 * original code left the size untouched there — callers must skip a null size
 * to stay verbatim).
 *
 * @param {{mode:string, color:string, imageUrl:string, imageName:string, imageFit:string}} state
 * @returns {{backgroundImage:string, backgroundSize:(string|null), backgroundColor:string, previewText:string}}
 */
export function computeBackgroundStyle(state) {
  if (state.mode === 'image' && state.imageUrl) {
    return {
      backgroundImage: `url("${state.imageUrl}")`,
      backgroundSize: state.imageFit === 'stretch' ? '100% 100%' : state.imageFit,
      backgroundColor: state.color,
      previewText: `Image background: ${state.imageName || 'selected image'}`,
    }
  }
  if (state.mode === 'aqueous') {
    return {
      backgroundImage: AQUEOUS_GRADIENT,
      backgroundSize: 'cover',
      backgroundColor: '#07324a',
      previewText: 'Aqueous theme applied. The environment feels cooler and underwater.',
    }
  }
  return {
    backgroundImage: 'none',
    backgroundSize: null,
    backgroundColor: state.color,
    previewText: `Solid color background: ${state.color}`,
  }
}

/**
 * Wire the Background Settings modal + viewport-background application.
 * Returns `{ applyStyle, getState }` (state exposed for tests/inspection).
 */
export function initBackgroundModal() {
  const container = document.getElementById('viewport-container') || document.body
  // Background modal — built lazily via createModal on first open.
  let modalCtrl = null
  const bgBody = document.getElementById('background-modal-body')
  // NOTE: do NOT removeAttribute('hidden') here — the body would render
  // inline in the page until the modal is opened. Unhide inside
  // `buildModalOnce()` instead, after createModal has reparented the body
  // into its detached overlay.
  const colorInput = document.getElementById('bg-color-input')
  const colorHexInput = document.getElementById('bg-color-hex')
  const imageInput = document.getElementById('bg-image-input')
  const imageFit = document.getElementById('bg-image-fit')
  const imageName = document.getElementById('bg-image-name')
  const preview = document.getElementById('bg-preview')

  const state = {
    mode: 'color',
    color: '#0d1117',
    imageUrl: '',
    imageName: '',
    imageFit: 'cover',
  }

  function applyStyle() {
    const style = computeBackgroundStyle(state)
    container.style.backgroundRepeat = 'no-repeat'
    container.style.backgroundPosition = 'center center'
    container.style.backgroundAttachment = 'fixed'
    container.style.backgroundImage = style.backgroundImage
    if (style.backgroundSize != null) container.style.backgroundSize = style.backgroundSize
    container.style.backgroundColor = style.backgroundColor
    if (preview) preview.textContent = style.previewText
  }

  function syncModal() {
    colorInput && (colorInput.value = state.color)
    colorHexInput && (colorHexInput.value = state.color)
    if (imageInput) imageInput.value = ''
    if (imageName) imageName.textContent = state.imageName || 'No image selected'
    if (imageFit) imageFit.value = state.imageFit
    if (preview) preview.textContent = computeBackgroundStyle(state).previewText
  }

  colorInput?.addEventListener('input', (event) => {
    state.mode = 'color'
    state.color = event.target.value
    colorHexInput && (colorHexInput.value = state.color)
    applyStyle()
  })

  colorHexInput?.addEventListener('input', (event) => {
    const value = event.target.value.trim()
    if (/^#[0-9a-fA-F]{6}$/.test(value)) {
      state.mode = 'color'
      state.color = value
      colorInput && (colorInput.value = value)
      applyStyle()
    }
  })

  imageInput?.addEventListener('change', (event) => {
    const file = event.target.files?.[0]
    if (!file) {
      state.mode = 'color'
      state.imageUrl = ''
      state.imageName = ''
      applyStyle()
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      state.mode = 'image'
      state.imageUrl = reader.result
      state.imageName = file.name
      imageName && (imageName.textContent = file.name)
      applyStyle()
    }
    reader.readAsDataURL(file)
  })

  imageFit?.addEventListener('change', (event) => {
    state.imageFit = event.target.value
    if (state.mode === 'image') applyStyle()
  })

  function buildModalOnce() {
    if (modalCtrl || !bgBody) return
    bgBody.removeAttribute('hidden')
    const cancelBtn = createButton({
      label: 'Cancel',
      variant: 'default',
      onClick: () => modalCtrl.close(),
    })
    const resetBtn = createButton({
      label: 'Reset',
      variant: 'default',
      onClick: () => {
        state.mode = 'color'
        state.color = '#0d1117'
        state.imageUrl = ''
        state.imageName = ''
        state.imageFit = 'cover'
        syncModal()
        applyStyle()
      },
    })
    const applyBtn = createButton({
      label: 'Apply',
      variant: 'primary',
      onClick: () => modalCtrl.close(),
    })
    modalCtrl = createModal({
      title: 'Background Settings',
      size: 'sm',
      body: bgBody,
      actions: [cancelBtn, resetBtn, applyBtn],
    })
  }

  document.getElementById('menu-view-background')?.addEventListener('click', () => {
    syncModal()
    buildModalOnce()
    modalCtrl?.open()
  })

  document.getElementById('background-modal-aqueous')?.addEventListener('click', () => {
    state.mode = 'aqueous'
    state.color = '#0d1117'
    state.imageUrl = ''
    state.imageName = ''
    syncModal()
    applyStyle()
  })

  container && applyStyle()

  return { applyStyle, getState: () => state }
}
