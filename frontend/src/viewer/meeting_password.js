/** Add a credential field only when this invitation actually requires one.
 * Hidden/disabled password inputs can still make name-only entry look like login.
 */
export function mountMeetingPassword({ document: doc = document, required }) {
  if (!required) return { field: null, dispose() {} }
  const row = doc.createElement('div')
  row.id = 'meeting-password-row'
  const label = doc.createElement('label')
  label.htmlFor = 'meeting-password'; label.textContent = 'Meeting password'
  const field = doc.createElement('input')
  field.id = 'meeting-password'; field.name = 'meeting-access-code'
  field.type = 'password'; field.maxLength = 128; field.required = true
  for (const [name, value] of Object.entries({
    autocomplete: 'off', autocorrect: 'off', autocapitalize: 'off', spellcheck: 'false',
    'data-1p-ignore': '', 'data-lpignore': 'true', 'data-bwignore': 'true', 'data-form-type': 'other',
  })) field.setAttribute(name, value)
  field.style.cssText = 'width:100%;padding:10px;opacity:1'
  row.append(label, field)
  doc.getElementById('join-error').before(row)
  return { field, dispose() { field.value = ''; row.remove() } }
}
