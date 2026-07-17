/** Workspace folders owned by simulation engines rather than by the user. */
export const SIM_FOLDER_NAMES = new Set([
  'autorefine',
  'benchmark_runs',
  'cando_autorefine',
  'cando_jobs',
  'lammps_jobs',
  'live_sessions',
  'md_chains',
  'md_jobs',
  'mrdna_jobs',
  'oxdna_jobs',
  'snupi_jobs',
])

/** True when a workspace-relative path is inside an engine-managed folder. */
export function isSimFolderPath(path = '') {
  const root = String(path).replaceAll('\\', '/').split('/').filter(Boolean)[0]
  return root.endsWith('_jobs') || SIM_FOLDER_NAMES.has(root)
}

export function visibleWorkspaceEntries(entries, showSimFolders = false) {
  return showSimFolders ? entries : entries.filter(entry => !isSimFolderPath(entry.path))
}
