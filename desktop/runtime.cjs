const path = require('node:path')

function parseOptions(argv) {
  const result = {}
  for (let i = 0; i < argv.length; i++) {
    if (['--workspace', '--profile', '--open'].includes(argv[i])) {
      const key = argv[i].slice(2)
      if (!argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`Missing ${argv[i]} value`)
      result[key] = argv[++i]
    } else if (argv[i] === '--standard-spheres') result.standardSpheres = true
    else if (argv[i] === '--validation') result.validation = true
  }
  if (result.validation && (!result.workspace || !result.profile)) throw new Error('Validation requires isolated --workspace and --profile directories')
  for (const key of ['workspace', 'profile']) {
    if (result[key] && !path.isAbsolute(result[key])) throw new Error(`--${key} must be absolute`)
  }
  if (result.open && (path.isAbsolute(result.open) || result.open.split(/[\\/]/).some(p => p === '..') || !/\.(nadoc|nass)$/i.test(result.open))) throw new Error('--open must name a workspace-relative .nadoc or .nass')
  return result
}

function localURL(value, origin) {
  try { const url = new URL(value); return url.origin === origin && !url.username && !url.password } catch { return false }
}

function launchURL(origin, file, { standardSpheres = false } = {}) {
  const url = new URL('/', origin)
  url.searchParams.set('desktop-debug', '1')
  url.searchParams.set('fast-backbone', standardSpheres ? '0' : '1')
  if (file) {
    url.searchParams.set('open', file)
    url.searchParams.set('open-type', /\.nass$/i.test(file) ? 'assembly' : 'part')
  }
  return url.href
}
module.exports = { parseOptions, localURL, launchURL }
