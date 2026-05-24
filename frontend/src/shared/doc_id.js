/**
 * Per-tab document identity for multi-document support (Phase 2).
 *
 * Each browser tab edits one backend "document".  The tab's doc id comes from
 * the ``?doc=<id>`` URL param.  A tab with no ``?doc=`` uses the backend default
 * document (legacy single-document behavior) — it sends no doc header, so the
 * backend resolves the ``__default__`` slot exactly as before Phase 2.
 *
 * Every API request stamps ``X-NADOC-Doc: <id>`` when an explicit id is present,
 * so the backend routes the request to this tab's session.  localStorage and
 * BroadcastChannel are likewise scoped by doc id so independent tabs never
 * clobber each other's cache or trigger each other's refetches.
 */

const _params = new URLSearchParams(location.search)
const _isEditor = location.pathname.includes('cadnano-editor')

// Resolve this tab's document id.
//  1. ?doc=<id> in the URL  → use it (a tab opened by another tab/window).
//  2. Standalone cadnano editor with no ?doc=  → null (default doc, legacy).
//  3. Main-app tab with no ?doc=  → adopt a STICKY per-tab id so two independently
//     opened tabs never share one backend document (which would cross-contaminate
//     saves). sessionStorage is per-tab and survives reload; the id is pinned into
//     the URL so child windows (cadnano editor, part editor) inherit it.
function _resolveDocId() {
  const explicit = _params.get('doc')
  if (explicit) return explicit
  if (_isEditor) return null
  const SK = 'nadoc:tab-doc'
  let id = null
  try { id = sessionStorage.getItem(SK) } catch { /* private mode */ }
  if (!id) {
    id = (crypto.randomUUID?.() ?? `${Date.now()}${Math.random().toString(16).slice(2)}`).replace(/-/g, '')
    try { sessionStorage.setItem(SK, id) } catch { /* ignore */ }
  }
  try {
    const u = new URL(location.href)
    u.searchParams.set('doc', id)          // preserves ?new / ?open / ?part-instance
    history.replaceState(history.state, '', u)
  } catch { /* ignore */ }
  return id
}

const _docId = _resolveDocId()

/** Explicit doc id for this tab, or null when on the default document. */
export function getDocId() { return _docId }

/** True when this tab owns an explicit (non-default) document. */
export function hasExplicitDoc() { return _docId != null }

/** Header to attach to API requests (empty object when on the default doc). */
export function docHeaders() {
  return _docId ? { 'X-NADOC-Doc': _docId } : {}
}

/**
 * Header for a SPECIFIC doc id (not necessarily this tab's own).  Used when a
 * tab must address another document for a one-off call — e.g. a part-editor tab
 * (which owns its own isolated doc for editing) reaching into the assembly's doc
 * to fetch its source design or save the edit back.  Null/empty → default doc.
 */
export function docHeadersFor(docId) { return docId ? { 'X-NADOC-Doc': docId } : {} }

/**
 * Scope a localStorage/Broadcast key to this tab's document.  The default doc
 * keeps the bare legacy key (``nadoc:design``) so Phase-1 recovery is unchanged;
 * explicit docs get a ``:<id>`` suffix.
 */
export function docKey(base) { return _docId ? `${base}:${_docId}` : base }

/** Like docKey, but for an explicitly named doc (not this tab's own).  Lets a
 *  part-editor tab read the ASSEMBLY tab's recovery cache (keyed by its doc). */
export function docKeyFor(base, docId) { return docId ? `${base}:${docId}` : base }

/** Mint a fresh doc id on the backend (for opening a new tab). */
export async function mintDocId() {
  try {
    const r = await fetch('/api/documents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
    if (r.ok) return (await r.json()).doc_id
  } catch { /* fall through */ }
  // Fallback: a client-side id still works (backend creates the session lazily).
  return (crypto.randomUUID?.() ?? String(Date.now())).replace(/-/g, '')
}
