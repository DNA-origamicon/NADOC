// @vitest-environment jsdom
import { it, expect, vi } from 'vitest'
import { twoBaseCSV, exportTwoBaseMaps } from './two_base_maps_export.js'
import { openMetricExportModal, downloadText, downloadHref } from './metric_export_modal.js'
vi.mock('./metric_export_modal.js',()=>({openMetricExportModal:vi.fn(),downloadText:vi.fn(),downloadHref:vi.fn()}))
const result={bases:['a','b'],rows:[[1,2,3,4,5,6]],frames:1}
it('exports all six coordinates with frame and base identities',async()=>{
  expect(twoBaseCSV(result).split('\n')[1]).toBe('"1","a","b","1","2","3","4","5","6"')
  openMetricExportModal.mockResolvedValue({data:true,png:false})
  await exportTwoBaseMaps(result,'job')
  expect(downloadText).toHaveBeenCalledWith('two_base_maps_job.csv',twoBaseCSV(result))
  expect(downloadHref).not.toHaveBeenCalled()
})
it('cancel does not download files',async()=>{
  downloadText.mockClear();openMetricExportModal.mockResolvedValue(null)
  await exportTwoBaseMaps(result,'job')
  expect(downloadText).not.toHaveBeenCalled()
})
