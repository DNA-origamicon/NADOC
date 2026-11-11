/** Show the current job identity without confusing it with a production parent. */
export function showWizardJobId(modal, jobId) {
  const title = modal?.header?.querySelector('.modal__title')
  if (!title) return
  title.querySelector('.wizard-job-id')?.remove()
  title.style.flexWrap = jobId ? 'wrap' : ''
  if (!jobId) return // New jobs receive their ID only when created.
  const label = title.ownerDocument.createElement('div')
  label.className = 'wizard-job-id'
  label.textContent = `Job ID: ${jobId}`
  label.style.cssText = 'flex-basis:100%;font-size:14px;font-weight:500;line-height:1.5;text-transform:none;letter-spacing:normal;user-select:text;overflow-wrap:anywhere'
  title.append(label)
}
