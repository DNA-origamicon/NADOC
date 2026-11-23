/** Native file extensions are fixed; folders retain their literal names. */
function extension(entry) {
  return entry.type === 'part' ? '.nadoc' : entry.type === 'assembly' ? '.nass' : ''
}

export function libraryRenameStem(entry, name = entry.path.split('/').pop()) {
  const suffix = extension(entry)
  return suffix && name.toLowerCase().endsWith(suffix) ? name.slice(0, -suffix.length) : name
}

export function libraryRenameFilename(entry, input) {
  const stem = libraryRenameStem(entry, input.trim()).trim()
  return stem ? stem + extension(entry) : ''
}
