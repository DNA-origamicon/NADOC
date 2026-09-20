import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Include uncommitted/new frontend files so A/B reports cannot share a misleading commit ID. */
export function frontendBuildInfo(frontendDir) {
  try {
    const root = resolve(frontendDir, '..')
    const git = args => execFileSync('git', args, { cwd: root, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 })
    const files = [...new Set(git(['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--',
      'frontend/src', 'frontend/*.html', 'frontend/package*.json', 'frontend/vite.config.js', 'frontend/build_info.js', 'frontend/viewer_test_server.js']).split('\0').filter(Boolean))].sort()
    const hash = createHash('sha256')
    for (const file of files) {
      hash.update(file); hash.update('\0')
      try { hash.update(readFileSync(resolve(root, file))) } catch { hash.update('<missing>') }
      hash.update('\0')
    }
    return { commit: git(['rev-parse', 'HEAD']).trim(), branch: git(['branch', '--show-current']).trim() || '(detached)',
      frontend_sha256: hash.digest('hex'), source_hash_scope: 'frontend files at Vite startup/build',
      dirty: !!git(['status', '--porcelain', '--', 'frontend']).trim() }
  } catch { return { commit: null, branch: null, frontend_sha256: null, dirty: null } }
}
