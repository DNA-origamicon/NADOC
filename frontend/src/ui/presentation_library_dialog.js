/** Fixed server/device library picker; no OS file chooser or imported script execution. */
export function initPresentationLibraryDialog({ root, library, onOpen }) {
  const dialog = document.createElement('dialog')
  dialog.className = 'presentation-library-dialog'
  dialog.setAttribute('aria-label', 'Compiled presentations')
  dialog.innerHTML = `<h3>Compiled presentations</h3><p>Open downloads all videos before playback and keeps a copy on this device when browser storage allows. Download the offline HTML file to reopen without NADOC.</p><p class="presentation-library-status" role="status"></p><progress hidden aria-label="Presentation download"></progress><div class="presentation-library-list"></div><button class="btn library-close">Close</button>`
  // Keep the modal outside sidebar mirrors; there must be one live picker.
  root.ownerDocument.body.append(dialog)
  const status = dialog.querySelector('[role="status"]'), list = dialog.querySelector('.presentation-library-list'), progress = dialog.querySelector('progress')
  let controller = null, generation = 0
  function close() { generation++; controller?.abort(); controller = null; dialog.close() }
  dialog.querySelector('.library-close').onclick = close
  dialog.addEventListener('cancel', event => { event.preventDefault(); close() })
  async function open() {
    controller?.abort(); controller = new AbortController()
    const signal = controller.signal, token = ++generation
    list.replaceChildren(); progress.hidden = true; status.textContent = 'Loading presentation library…'
    dialog.showModal()
    // Ask the browser to retain stored presentations. Denial is normal and never
    // blocks playback; downloadable HTML remains the independent offline copy.
    void navigator.storage?.persist?.().catch(() => {})
    try {
      const result = await library.list(signal)
      if (token !== generation) return
      status.textContent = result.notice
      if (!result.entries.length) list.textContent = 'No compiled presentations yet. Compile a presentation or trajectory keyframe first.'
      for (const entry of result.entries) {
        const row = document.createElement('div'), label = document.createElement('div'), detail = document.createElement('small'), button = document.createElement('button')
        label.textContent = entry.name
        detail.textContent = `${entry.kind === 'keyframe' ? 'Trajectory keyframe' : 'Presentation'} · ${(entry.size / 1048576).toFixed(1)} MiB · ${new Date(entry.created_at).toLocaleString()} · ${entry.deviceSaved ? 'Saved on this device' : 'On server'}`
        button.className = 'btn'; button.textContent = entry.deviceSaved ? 'Open local copy' : 'Download and open'
        button.onclick = async () => {
          for (const item of list.querySelectorAll('button')) item.disabled = true
          status.textContent = 'Opening presentation…'
          try {
            const opened = await library.open(entry, { signal, onProgress(done, total) {
              if (token !== generation) return
              progress.hidden = false; progress.max = total || 1; progress.value = done
              status.textContent = `Downloading presentation… ${(done / 1048576).toFixed(1)} / ${(total / 1048576).toFixed(1)} MiB`
            } })
            if (token !== generation) return
            onOpen(opened.data, entry, opened.notice)
            close()
          } catch (error) {
            if (token !== generation) return
            status.textContent = `Could not open presentation: ${error.message}`
            for (const item of list.querySelectorAll('button')) item.disabled = false
          } finally { if (token === generation) progress.hidden = true }
        }
        row.append(label, detail, button); list.append(row)
      }
    } catch (error) { if (token === generation) status.textContent = `Could not load library: ${error.message}` }
  }
  return { open, close, dispose() { close(); dialog.remove() } }
}
