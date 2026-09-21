/** Download only an announced revision; never replace a valid scene with stale bytes. */
export async function loadMeetingRevision({ viewer, base, revision, fetch: request = fetch, signal, isCurrent = () => true }) {
  const response = await request(`${base}/scene?revision=${encodeURIComponent(revision)}`, { signal })
  if (response.status === 409) return false
  if (!response.ok) throw new Error('Could not download the presenter’s updated visualization')
  const size = Number(response.headers.get('Content-Length'))
  if (!Number.isFinite(size) || size <= 0 || size > 512 * 1024 * 1024) throw new Error('Invalid presentation update size')
  const blob = await response.blob()
  if (!isCurrent()) return false
  if (blob.size !== size) throw new Error('Incomplete presentation update')
  const loaded = await viewer.loadFile(new File([blob], 'Shared design.nadocview'), { preserveCamera: true, expectedHash: revision, isCurrent })
  if (!loaded && isCurrent()) throw new Error('Could not open the presenter’s updated visualization')
  return !!loaded
}
