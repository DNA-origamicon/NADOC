import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/recent_files.js', () => ({
  getRecentProteinImports: vi.fn(() => []),
  addRecentProteinCode: vi.fn(),
  addRecentProteinFile: vi.fn(),
}))

import { getRecentProteinImports } from '../api/recent_files.js'
import { openImportPdbModal } from './import_pdb_modal.js'

describe('openImportPdbModal cancellation', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    getRecentProteinImports.mockReturnValue([])
  })

  it('aborts the active request and ignores a response that arrives after close', async () => {
    let resolveImport
    const onResult = vi.fn(args => new Promise(resolve => {
      resolveImport = () => resolve({ imported: { protein: true } })
      expect(args.signal).toBeInstanceOf(AbortSignal)
    }))
    const modal = openImportPdbModal({ onResult })
    const input = document.querySelector('input[type="text"]')
    input.value = '1ABC'
    const download = [...document.querySelectorAll('button')]
      .find(button => button.textContent === 'Download & Import')
    download.click()
    await Promise.resolve()

    modal.close()
    expect(modal.signal.aborted).toBe(true)
    resolveImport()
    await Promise.resolve()
    await Promise.resolve()
    expect(document.body.textContent).not.toContain('Import failed')
  })

  it('passes the selected library placement and a cancellation signal', async () => {
    const onResult = vi.fn().mockResolvedValue({
      imported: { protein: true }, protein: { name: 'x' }, protein_placement: 'library',
    })
    openImportPdbModal({ onResult })
    document.getElementById('pdb-protein-placement').value = 'library'
    const input = document.querySelector('input[type="text"]')
    input.value = '1ABC'
    const download = [...document.querySelectorAll('button')]
      .find(button => button.textContent === 'Download & Import')
    download.click()
    await Promise.resolve()
    expect(onResult.mock.calls[0][0].proteinPlacement).toBe('library')
    expect(onResult.mock.calls[0][0].signal).toBeInstanceOf(AbortSignal)
  })

  it('reuses an RCSB id for the Remove DNA step instead of re-uploading content', async () => {
    getRecentProteinImports.mockReturnValue([
      { kind: 'code', code: '8SCP', ts: Date.now() },
    ])
    const onResult = vi.fn()
      .mockResolvedValueOnce({
        needs_dna_decision: true,
        has_dna: true,
        has_protein: true,
        pdb_id: '8SCP',
        name: '8SCP',
      })
      .mockResolvedValueOnce({
        imported: { protein: true },
        protein: { name: '8SCP', atom_count: 9530 },
        protein_placement: 'free',
      })
    openImportPdbModal({ onResult })
    const recent = [...document.querySelectorAll('button')]
      .find(button => button.textContent.includes('8SCP'))
    recent.click()
    await vi.waitFor(() => expect(onResult).toHaveBeenCalledTimes(1))
    const remove = [...document.querySelectorAll('button')]
      .find(button => button.textContent === 'Remove DNA')
    remove.click()
    await vi.waitFor(() => expect(onResult).toHaveBeenCalledTimes(2))
    expect(onResult.mock.calls[1][0]).toMatchObject({
      pdbId: '8SCP',
      name: '8SCP',
      removeDnaFromProtein: true,
    })
    expect(onResult.mock.calls[1][0].content).toBeUndefined()
  })
})
