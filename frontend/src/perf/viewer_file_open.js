/** Native workspace paths follow the same loader as File → Open, including
 * part/assembly lifecycle, geometry, camera framing, and progress/error reporting. */
export function viewerFilePath(value) {
  if (typeof value !== 'string' || !value || value.length > 2048 || /[\x00-\x1f]/.test(value)) throw new Error('Provide a native workspace file path')
  const path = value.replaceAll('\\', '/')
  if (path.startsWith('/') || /^[a-z]:/i.test(path) || path.split('/').some(part => part === '..' || part === '' || part === '.')) throw new Error('Use a workspace-relative path without traversal')
  if (!/\.(nadoc|nass)$/i.test(path)) throw new Error('Native file loading supports .nadoc parts and .nass assemblies')
  return path
}

export async function openViewerFile({ path, getFileOpen }) {
  path = viewerFilePath(path)
  const fileOpen = getFileOpen()
  if (!fileOpen) throw new Error('Viewer is still initializing; retry when ready')
  const ok = /\.nass$/i.test(path) ? await fileOpen.openAssemblyFromServer(path) : await fileOpen.openPartFromServer(path)
  if (!ok) throw new Error('File load failed or assembly has missing parts; inspect the file-load dialog')
  return { path }
}
