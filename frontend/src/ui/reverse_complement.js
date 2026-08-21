import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'

const COMPLEMENT = Object.freeze({
  A: 'T', T: 'A', U: 'A', C: 'G', G: 'C',
  R: 'Y', Y: 'R', S: 'S', W: 'W', K: 'M', M: 'K',
  B: 'V', V: 'B', D: 'H', H: 'D', N: 'N',
})

/** Return an uppercase DNA reverse complement; whitespace is ignored. */
export function reverseComplement(value) {
  const sequence = String(value ?? '').replace(/\s+/g, '').toUpperCase()
  if (!sequence) return ''
  if ([...sequence].some(base => !COMPLEMENT[base])) {
    throw new Error('Use DNA/IUPAC bases only (A–Z codes such as A, C, G, T, or N).')
  }
  return [...sequence].reverse().map(base => COMPLEMENT[base]).join('')
}

export function initReverseComplement() {
  const heading = document.getElementById('reverse-complement-heading')
  const body = document.getElementById('reverse-complement-body')
  const arrow = document.getElementById('reverse-complement-arrow')
  const input = document.getElementById('reverse-complement-input')
  const output = document.getElementById('reverse-complement-output')
  const copy = document.getElementById('reverse-complement-copy')
  const status = document.getElementById('reverse-complement-status')
  if (!input || !output || !copy) return null

  let collapsed = getSectionCollapsed('right', 'reverse-complement-section', false)
  const applyCollapsed = () => {
    if (body) body.hidden = collapsed
    heading?.setAttribute('aria-expanded', String(!collapsed))
    arrow?.classList.toggle('is-collapsed', collapsed)
  }
  const toggleCollapsed = () => {
    collapsed = !collapsed
    applyCollapsed()
    setSectionCollapsed('right', 'reverse-complement-section', collapsed)
  }
  heading?.addEventListener('click', toggleCollapsed)
  heading?.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    toggleCollapsed()
  })
  applyCollapsed()

  const update = () => {
    try {
      output.value = reverseComplement(input.value)
      copy.disabled = !output.value
      if (status) status.textContent = output.value ? `${output.value.length} nt` : ''
    } catch (error) {
      output.value = ''
      copy.disabled = true
      if (status) status.textContent = error.message
    }
  }
  input.addEventListener('input', update)
  output.addEventListener('click', () => output.select())
  copy.addEventListener('click', async () => {
    if (!output.value) return
    try {
      await navigator.clipboard.writeText(output.value)
    } catch {
      output.select()
      document.execCommand?.('copy')
    }
    if (status) status.textContent = 'Copied!'
  })
  update()
  return { update, toggleCollapsed }
}
