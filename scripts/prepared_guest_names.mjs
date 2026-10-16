import { createRequire } from 'node:module'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { RegExpMatcher, englishDataset, englishRecommendedTransformers } = require('obscenity')
const matcher = new RegExpMatcher({ ...englishDataset.build(), ...englishRecommendedTransformers })
/** Keep display spelling; normalize only the screening copy. No external requests. */
export function screenGuestName(value) {
  if (typeof value !== 'string') throw new Error('Enter a display name of 1–40 characters.')
  const name = value.normalize('NFC').trim()
  if (!name || [...name].length > 40 || /[\p{Cc}\p{Cf}]/u.test(name)) throw new Error('Use 1–40 visible characters for your display name.')
  // Exact name tokens only: never exempt an entire string containing a name.
  const screening = name.normalize('NFKC').replace(/\b(?:dick|dickinson|penistone)\b/gi, 'Guest')
  if (matcher.hasMatch(screening) || matcher.hasMatch(screening.replace(/[\p{P}\p{Z}]/gu, ''))) throw new Error('Please choose another display name, or use a neutral nickname such as Guest 123.')
  return name
}
