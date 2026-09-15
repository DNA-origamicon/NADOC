import {it,expect,vi} from 'vitest'
import {confirmElectrodeProtocol,ELECTRODE_PROTOCOL} from './namd_electrode_protocol.js'
it('warns on old protocols, supports cancel and deliberate continuation without changing the saved job',()=>{
  const job={protocol:'equilibrium_aware_namd'},confirm=vi.fn(()=>false)
  expect(confirmElectrodeProtocol({enabled:true,job,confirm})).toBe(false)
  expect(confirm.mock.calls[0][0]).toContain('saved job unchanged')
  confirm.mockReturnValue(true)
  expect(confirmElectrodeProtocol({enabled:true,job,confirm})).toBe(true)
  expect(job.protocol).toBe('equilibrium_aware_namd')
  confirm.mockClear()
  expect(confirmElectrodeProtocol({enabled:true,job:{protocol:ELECTRODE_PROTOCOL},confirm})).toBe(true)
  expect(confirmElectrodeProtocol({enabled:false,job,confirm})).toBe(true)
  expect(confirm).not.toHaveBeenCalled()
})
