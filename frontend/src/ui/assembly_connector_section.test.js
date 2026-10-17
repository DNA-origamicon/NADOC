import { afterEach, describe, expect, it, vi } from 'vitest'
import { createAssemblyConnectorSection } from './assembly_connector_section.js'

afterEach(() => { document.body.innerHTML = '' })

function mount(connectors, joints = []) {
  const api = { deleteInstanceConnector: vi.fn(async () => {}) }
  const confirm = vi.fn(async () => true)
  const section = createAssemblyConnectorSection({ id: 'part', interface_points: connectors }, joints, { api, confirm })
  document.body.appendChild(section)
  return { section, header: section.firstElementChild, list: section.lastElementChild, api, confirm }
}

describe('assembly connector section', () => {
  it('defers hidden rows and mate scans, then retains rows across closing and reopening', () => {
    const joints = [{ instance_b_id: 'part', connector_b_label: 'used' }]
    const scan = vi.spyOn(joints, 'filter')
    const { header, list } = mount([{ label: 'used' }, { label: 'free' }], joints)
    expect(header.textContent).toContain('Connectors (2)')
    expect(list.children).toHaveLength(0)
    expect(scan).not.toHaveBeenCalled()
    header.click()
    expect(list.children).toHaveLength(2)
    expect(list.style.display).toBe('')
    const original = list.firstElementChild
    header.click()
    expect(list.style.display).toBe('none')
    header.click()
    expect(list.firstElementChild).toBe(original)
    expect(scan).toHaveBeenCalledTimes(2)
  })

  it('preserves used-connector confirmation, cancellation and free deletion', async () => {
    const { header, list, api, confirm } = mount([{ label: 'used' }, { label: 'free' }], [
      { instance_a_id: 'part', connector_a_label: 'used' },
      { instance_b_id: 'part', connector_b_label: 'used' },
    ])
    header.click()
    const [used, free] = list.querySelectorAll('button')
    confirm.mockResolvedValueOnce(false)
    used.click()
    await Promise.resolve()
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ message: 'Connector "used" is used in 2 mate(s). Delete anyway?' }))
    expect(api.deleteInstanceConnector).not.toHaveBeenCalled()
    used.click()
    await Promise.resolve()
    expect(api.deleteInstanceConnector).toHaveBeenLastCalledWith('part', 'used')
    free.click()
    expect(api.deleteInstanceConnector).toHaveBeenLastCalledWith('part', 'free')
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('shows an empty section when opened', () => {
    const { header, list } = mount([])
    expect(list.textContent).toBe('')
    header.click()
    expect(list.textContent).toBe('No connectors defined')
  })
})
