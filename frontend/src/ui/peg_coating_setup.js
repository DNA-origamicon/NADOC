/** Review the current coating without preparing or launching an engine job. */
export function initPegCoatingSetup({ reviewSetup, getSurface, getCoating }) {
  const button = document.getElementById('oxdna-peg-review')
  const result = document.getElementById('oxdna-peg-review-result')
  const controls = document.getElementById('oxdna-peg-controls')
  if (!button || !result || !controls) return
  let revision = 0
  const invalidate = () => { revision++; result.textContent = '' }
  document.getElementById('oxdna-floor-body')?.addEventListener('input', invalidate)
  document.getElementById('oxdna-floor-body')?.addEventListener('change', invalidate)
  button.addEventListener('click', async () => {
    const surface = getSurface(), coating = getCoating()
    if (!surface?.enabled || !coating?.enabled) {
      result.textContent = 'Enable the hard surface and PEG coating first.'
      return
    }
    const invalid = [...document.querySelectorAll('#oxdna-peg-controls input')]
      .find(input => !input.checkValidity() || input.value.trim() === '')
    if (invalid) {
      result.textContent = 'Enter valid values in all surface and PEG fields before reviewing.'
      invalid.focus()
      return
    }
    const surface_strands = Object.fromEntries([
      'material', 'enabled', 'segments', 'bondLengthNm', 'beadDiameterNm', 'terminalChargeE',
      'shape', 'sizeNm', 'densityPerUm2', 'offsetXNm', 'offsetYNm', 'seed', 'subjectToField',
    ].map(key => [key, coating[key]]))
    const snapshot = ++revision
    button.disabled = true
    result.textContent = 'Reviewing setup…'
    try {
      const review = await reviewSetup({
        surface: { dir: surface.dir, position_nm: surface.positionNm, offset_nm: surface.offsetNm, stiff: surface.stiff },
        surface_strands,
        backend: document.getElementById('oxdna-jobs-backend')?.value || 'CPU',
      })
      if (snapshot !== revision) return
      if (!review) throw new Error('Setup review failed. Check the values and try again.')
      const summary = review.summary
      result.textContent = `Setup only · ${summary.requested_chains} requested chains · ${summary.requested_beads} beads. No job created.\n` +
        review.barriers.map(barrier => barrier.message).join('\n')
    } catch (error) {
      if (snapshot === revision) result.textContent = error.message
    } finally { button.disabled = false }
  })
}
