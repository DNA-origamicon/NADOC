/**
 * Annotation callout icons. Static, self-coloured 24×24 SVG markup (trusted
 * literals, never user input) so an icon reads identically in the sidebar
 * picker and inside a callout regardless of the entry's frame colour.
 */

const S = (inner) => inner

export const ANNOTATION_ICONS = Object.freeze([
  { key: 'warning', label: 'Warning', svg: S(
    '<path d="M12 2.5 22.5 20.5H1.5Z" fill="#f2b705" stroke="#8a6500" stroke-width="1.4" stroke-linejoin="round"/>' +
    '<rect x="11" y="8.5" width="2" height="6.5" rx="1" fill="#1b1b1b"/><circle cx="12" cy="17.6" r="1.3" fill="#1b1b1b"/>') },
  { key: 'attention', label: 'Attention', svg: S(
    '<circle cx="12" cy="12" r="10" fill="#e5483d" stroke="#8f1d15" stroke-width="1.4"/>' +
    '<rect x="10.9" y="5.6" width="2.2" height="8" rx="1.1" fill="#fff"/><circle cx="12" cy="17.4" r="1.5" fill="#fff"/>') },
  { key: 'check', label: 'Green check', svg: S(
    '<circle cx="12" cy="12" r="10" fill="#2ea043" stroke="#17672a" stroke-width="1.4"/>' +
    '<path d="m6.8 12.4 3.5 3.5 6.9-7.4" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>') },
  { key: 'cross', label: 'Red X', svg: S(
    '<circle cx="12" cy="12" r="10" fill="#e5483d" stroke="#8f1d15" stroke-width="1.4"/>' +
    '<path d="m8 8 8 8M16 8l-8 8" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>') },
  { key: 'info', label: 'Info', svg: S(
    '<circle cx="12" cy="12" r="10" fill="#388bfd" stroke="#1a4f9c" stroke-width="1.4"/>' +
    '<circle cx="12" cy="7.2" r="1.5" fill="#fff"/><rect x="10.9" y="10.4" width="2.2" height="7.4" rx="1.1" fill="#fff"/>') },
  { key: 'question', label: 'Question', svg: S(
    '<circle cx="12" cy="12" r="10" fill="#8957e5" stroke="#4c2889" stroke-width="1.4"/>' +
    '<path d="M9 9.4a3 3 0 1 1 4.6 2.5c-1 .6-1.6 1.2-1.6 2.3" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>' +
    '<circle cx="12" cy="17.6" r="1.35" fill="#fff"/>') },
  { key: 'star', label: 'Star', svg: S(
    '<path d="m12 2.6 2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.2 1.2-6.5L2.5 9.5l6.6-.9Z" fill="#f2b705" stroke="#8a6500" stroke-width="1.4" stroke-linejoin="round"/>') },
  { key: 'flag', label: 'Flag', svg: S(
    '<path d="M5 21.5V3" stroke="#6e7681" stroke-width="2" stroke-linecap="round"/>' +
    '<path d="M5.6 4h13l-3 4.3 3 4.3h-13Z" fill="#f0883e" stroke="#a04a0f" stroke-width="1.3" stroke-linejoin="round"/>') },
  { key: 'pin', label: 'Pin', svg: S(
    '<path d="M12 22c-4.6-5.2-7-8.7-7-12a7 7 0 0 1 14 0c0 3.3-2.4 6.8-7 12Z" fill="#e5483d" stroke="#8f1d15" stroke-width="1.4" stroke-linejoin="round"/>' +
    '<circle cx="12" cy="10" r="2.6" fill="#fff"/>') },
])

const BY_KEY = new Map(ANNOTATION_ICONS.map(icon => [icon.key, icon]))

export const isAnnotationIcon = key => BY_KEY.has(key)

/** `<svg>` markup for an icon key, or '' for none/unknown. */
export function annotationIconMarkup(key, size = 18) {
  const icon = BY_KEY.get(key)
  if (!icon) return ''
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true" focusable="false">${icon.svg}</svg>`
}
