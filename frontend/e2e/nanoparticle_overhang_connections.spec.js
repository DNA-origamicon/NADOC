import { expect, test } from '@playwright/test'
import { copyFile, mkdir, rm } from 'node:fs/promises'
import path from 'node:path'

const SOURCE = path.resolve(import.meta.dirname, '../../workspace/NP_test.nadoc')
const SCRATCH_DIR = path.resolve(import.meta.dirname, '../../workspace/playwright_tests')
const FIXTURE = path.join(SCRATCH_DIR, '__e2e__NP_test_overhang_connections.nadoc')

test.describe('nanoparticle handle overhang connection versions', () => {
  test.beforeAll(async () => {
    await mkdir(SCRATCH_DIR, { recursive: true })
    await copyFile(SOURCE, FIXTURE)
  })
  test.afterAll(async () => { await rm(FIXTURE, { force: true }) })

  test('creates versions, applies one-at-a-time, and collectively relaxes', async ({ page }) => {
    test.setTimeout(240_000)
    await page.goto('/')
    await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles?.conjugation?.loadDesign))
    const loaded = await page.evaluate(file => window.__nadocTest.nanoparticles.conjugation.loadDesign(file), FIXTURE)
    const particle = loaded.design.nanoparticles[0]
    // NP_test currently contains two applied anchors. Exercise its collective
    // relaxation before resetting the fixture and verify every other surface
    // handle is regenerated from the relaxed nanoparticle pose.
    const existingApplied = loaded.design.nanoparticle_connection_versions
      .filter(version => version.nanoparticle_id === particle.id && version.applied)
    if (existingApplied.length >= 2) {
      const relaxedFixture = await page.evaluate(id =>
        window.__nadocTest.nanoparticles.conjugation.relaxConnections(id), particle.id)
      expect(relaxedFixture.dna_avoidance_shift_magnitude_nm).toBeGreaterThanOrEqual(0)
      const freeHandleError = await page.evaluate(id => {
        const design = window.__nadocTest.store.getState().currentDesign
        const particle = design.nanoparticles.find(item => item.id === id)
        const conjugation = design.nanoparticle_conjugations.find(item => item.nanoparticle_id === id)
        const helices = new Map(design.helices.map(helix => [helix.id, helix]))
        const m = particle.pose.values
        const distance = particle.diameter_nm / 2 + conjugation.spacer_nm
        let maximum = 0
        for (const record of conjugation.surface_strands.filter(item => !item.bound_overhang_id)) {
          const local = record.site_local.map(value => value * distance)
          const expected = [
            m[0] * local[0] + m[1] * local[1] + m[2] * local[2] + m[3],
            m[4] * local[0] + m[5] * local[1] + m[6] * local[2] + m[7],
            m[8] * local[0] + m[9] * local[1] + m[10] * local[2] + m[11],
          ]
          const start = helices.get(record.helix_id).axis_start
          const actual = [start.x, start.y, start.z]
          maximum = Math.max(maximum, ...actual.map((value, i) => Math.abs(value - expected[i])))
        }
        return maximum
      }, particle.id)
      expect(freeHandleError).toBeLessThan(1e-8)
      // Restore the disposable source state so the remaining single-anchor
      // workflow is independent of this two-anchor relaxation check.
      await page.evaluate(file =>
        window.__nadocTest.nanoparticles.conjugation.loadDesign(file), FIXTURE)
    }
    // Clean through the public API so any applied duplex is reversibly torn
    // down; editing JSON flags directly would leave relocated topology behind.
    await page.evaluate(async id => {
      const api = window.__nadocTest.nanoparticles.conjugation
      const existing = await api.versions(id)
      for (const version of existing.versions) await api.deleteVersion(id, version.id)
      // Rebuild the disposable handles at the particle's current pose. Handles
      // restored from a historical applied snapshot intentionally retain that
      // snapshot geometry and are unsuitable as a fresh single-anchor fixture.
      const design = window.__nadocTest.store.getState().currentDesign
      const prior = design.nanoparticle_conjugations.find(item => item.nanoparticle_id === id)
      await api.apply(id, {
        scheme: prior.scheme, sequence: prior.sequence,
        count: prior.requested_count, attach_end: prior.attach_end,
        spacer_nm: prior.spacer_nm, seed: prior.distribution_seed,
      })
    }, particle.id)
    loaded.design = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign)
    const conjugation = loaded.design.nanoparticle_conjugations.find(c => c.nanoparticle_id === particle.id)
    expect(conjugation.surface_strands.length).toBeGreaterThan(1)
    expect(loaded.design.overhangs.length).toBeGreaterThan(0)

    await page.evaluate(() => {
      document.getElementById('welcome-screen')?.classList.add('hidden')
      const panel = document.getElementById('right-panel')
      if (panel) { panel.style.display = 'block'; panel.classList.remove('hidden') }
      const tabs = document.getElementById('right-tab-strip')
      if (tabs) { tabs.style.display = 'flex'; tabs.classList.remove('locked-inactive') }
      const section = document.getElementById('overhang-connections-section')
      if (section) { section.style.display = 'block'; section.scrollIntoView() }
      document.getElementById('oconn-heading').click()
      document.getElementById('oconn-body').style.display = 'block'
    })
    await page.locator('#oconn-endpoint-mode').selectOption('nanoparticle', { force: true })
    await expect(page.locator('#oconn-np-select')).toHaveCount(0)
    await expect(page.locator('#oconn-np-strand')).toHaveCount(0)
    await page.evaluate(() => document.getElementById('oconn-button-box').click())
    await expect(page.locator('#oconn-popover .ct-option:not([hidden])')).toHaveCount(2)
    const pickerLayout = await page.evaluate(() => {
      const picker = document.getElementById('oconn-popover').getBoundingClientRect()
      const panel = document.getElementById('right-panel')
      const tabs = document.getElementById('right-tab-strip')
      return {
        width: picker.width,
        columns: getComputedStyle(document.getElementById('oconn-popover')).gridTemplateColumns,
        panelZ: Number(getComputedStyle(panel).zIndex),
        tabsZ: Number(getComputedStyle(tabs).zIndex),
      }
    })
    expect(pickerLayout.width).toBeLessThan(420)
    expect(pickerLayout.columns.split(' ')).toHaveLength(2)
    expect(pickerLayout.panelZ).toBeGreaterThan(pickerLayout.tabsZ)
    const matchedButtonStyles = await page.evaluate(() => {
      const pairs = [
        ['oconn-generate', 'oconn-np-add'],
        ['oconn-apply', 'oconn-np-apply'],
        ['oconn-secondary', 'oconn-np-relax'],
      ]
      return pairs.map(([regularId, nanoparticleId]) => {
        const regular = document.getElementById(regularId)
        const nanoparticle = document.getElementById(nanoparticleId)
        const disabled = [regular.disabled, nanoparticle.disabled]
        regular.disabled = false
        nanoparticle.disabled = false
        const pick = element => {
          const style = getComputedStyle(element)
          return [style.backgroundColor, style.padding, style.borderRadius, style.fontSize]
        }
        const styles = [pick(regular), pick(nanoparticle)]
        regular.disabled = disabled[0]
        nanoparticle.disabled = disabled[1]
        return styles
      })
    })
    for (const [regular, nanoparticle] of matchedButtonStyles) expect(nanoparticle).toEqual(regular)
    const handle = conjugation.surface_strands[0]
    const overhang = loaded.design.overhangs[0]
    await page.locator('#oconn-select-a').selectOption(handle.strand_id, { force: true })
    await page.locator('#oconn-select-b').selectOption(overhang.id, { force: true })
    await expect(page.locator('#oconn-popover .ct-option.is-forbidden:not([hidden])')).toHaveCount(1)
    const selectedVariant = await page.evaluate(() => {
      const allowed = document.querySelector('#oconn-popover .ct-option:not([hidden]):not(.is-forbidden)')
      allowed.click()
      return allowed.dataset.variant
    })
    await expect(page.locator('#oconn-seq-input-a')).not.toHaveValue('')
    await expect(page.locator('#oconn-seq-input-b')).not.toHaveValue('')
    const tetherBefore = await page.evaluate(id =>
      window.__nadocTest.nanoparticles.conjugation.get(id), particle.id)
    expect(tetherBefore.tether_measurements.length).toBeGreaterThan(0)
    expect(tetherBefore.tether_measurements.every(m => m.render_endpoint_error_nm === 0)).toBe(true)
    await expect(page.locator('#oconn-np-add')).toBeEnabled()
    await page.evaluate(() => document.getElementById('oconn-np-add').click())
    await expect(page.locator('#oconn-np-list')).toContainText('V1')
    await expect(page.locator('#oconn-np-list')).toContainText('Unapplied')

    await page.evaluate(() => document.querySelector('#oconn-np-list .oconn-version-row').click())
    await page.evaluate(() => document.getElementById('oconn-np-apply').click())
    await expect(page.locator('#oconn-np-list')).toContainText('Applied')

    await page.evaluate(() => document.getElementById('oconn-np-add').click())
    await expect(page.locator('#oconn-np-list')).toContainText('V2')
    const rows = page.locator('#oconn-np-list .oconn-version-row')
    await page.evaluate(() => document.querySelectorAll('#oconn-np-list .oconn-version-row')[1].click())
    await page.evaluate(() => document.getElementById('oconn-np-apply').click())
    const appliedVersions = await page.evaluate(id => window.__nadocTest.nanoparticles.conjugation.versions(id), particle.id)
    expect(appliedVersions.versions.filter(version => version.applied)).toHaveLength(1)
    expect(appliedVersions.versions.find(version => version.name === 'V1').applied).toBe(false)
    const materialized = await page.evaluate(id => {
      const design = window.__nadocTest.store.getState().currentDesign
      const version = design.nanoparticle_connection_versions.find(
        item => item.nanoparticle_id === id && item.applied)
      const duplex = design.duplexes.find(item => item.id === version.duplex_id)
      const npOverhang = design.nanoparticle_conjugations
        .find(item => item.nanoparticle_id === id).surface_strands
        .find(item => item.strand_id === version.strand_id).overhang_id
      const domainFor = overhangId => design.strands
        .flatMap(strand => strand.domains)
        .find(domain => domain.overhang_id === overhangId)
      return {
        version, duplex,
        npDirection: domainFor(npOverhang).direction,
        targetDirection: domainFor(version.overhang_id).direction,
      }
    }, particle.id)
    expect(materialized.version.direct_variant).toBe(selectedVariant)
    expect(materialized.version.target_attach).toBe('root')
    expect(materialized.version.nanoparticle_attach).toBe(
      selectedVariant === 'root-to-root'
        ? (conjugation.attach_end === '5p' ? 'root' : 'free_end')
        : (conjugation.attach_end === '5p' ? 'free_end' : 'root'))
    expect(materialized.duplex.connection_type).toBe(`nanoparticle-${selectedVariant}`)
    expect(materialized.npDirection).not.toBe(materialized.targetDirection)

    const after = await page.evaluate(id => window.__nadocTest.nanoparticles.conjugation.versions(id), particle.id)
    const measurement = after.versions.find(version => version.applied).duplex_measurement
    expect(measurement.native_position_match).toBe(true)
    expect(measurement.paired_base_count).toBeGreaterThan(0)
    expect(measurement.backbone_rms_error_nm).toBe(0)
    expect(measurement.mean_backbone_separation_nm).toBeGreaterThan(1)
    const tetherAfter = await page.evaluate(id =>
      window.__nadocTest.nanoparticles.conjugation.get(id), particle.id)
    const stretched = tetherAfter.tether_measurements.find(m => m.strand_id === handle.strand_id)
    const initial = tetherBefore.tether_measurements.find(m => m.strand_id === handle.strand_id)
    expect(stretched.bound).toBe(true)
    expect(stretched.measured_length_nm).not.toBe(initial.measured_length_nm)
    expect(tetherAfter.tether_measurements.every(m => m.render_endpoint_error_nm === 0)).toBe(true)
    // Exercise the actual selected-object gizmo and Apply button.  The live
    // preview and backend must use the same exact backbone joint, otherwise
    // the nanoparticle visibly jumps when Apply replaces preview geometry.
    await page.evaluate(id => window.__nadocTest.nanoparticles.select(id), particle.id)
    await expect.poll(() => page.evaluate(() =>
      window.__nadocTest.nanoparticles.gizmoAttached())).toBe(true)
    expect(await page.evaluate(() => window.__nadocTest.nanoparticles.gizmoSetTransform(
      [20, -5, 3], [0, 0, 0, 1]))).toBe(true)
    const previewPosition = await page.evaluate(() =>
      window.__nadocTest.nanoparticles.rendered()[0].position)
    // `gizmoApply` is the awaited form of the same controller action dispatched
    // by #mr-apply-btn (the button routing itself has a focused unit test).
    expect(await page.evaluate(() =>
      window.__nadocTest.nanoparticles.gizmoApply())).toBe(true)
    await expect.poll(async () => {
      const committed = await page.evaluate(() =>
        window.__nadocTest.nanoparticles.rendered()[0].position)
      return Math.max(...committed.map((value, index) => Math.abs(value - previewPosition[index])))
    }).toBeLessThan(1e-6)
    const afterJointMove = await page.evaluate(id =>
      window.__nadocTest.nanoparticles.conjugation.get(id), particle.id)
    const movedTether = afterJointMove.tether_measurements.find(m => m.strand_id === handle.strand_id)
    expect(movedTether.bound).toBe(true)
    expect(Math.abs(movedTether.measured_length_nm - initial.measured_length_nm)).toBeLessThan(0.25)
    const movedVersion = await page.evaluate(id =>
      window.__nadocTest.nanoparticles.conjugation.versions(id), particle.id)
    expect(movedVersion.versions.find(version => version.applied).duplex_measurement.native_position_match).toBe(true)
    const persistedBeforeSave = await page.evaluate(({ strandId, overhangId }) => {
      const state = window.__nadocTest.store.getState()
      const cluster = state.currentDesign.cluster_transforms.find(
        item => item.overhang_duplex_driver_id === overhangId)
      const beads = state.currentGeometry
        .filter(item => item.strand_id === strandId || item.overhang_id === overhangId)
        .map(item => ({ strand_id: item.strand_id, bp_index: item.bp_index,
          backbone_position: item.backbone_position }))
      return { cluster, beads }
    }, { strandId: handle.strand_id, overhangId: overhang.id })
    expect(persistedBeforeSave.cluster).toBeTruthy()
    await page.evaluate(file => window.__nadocTest.nanoparticles.conjugation.saveDesign(file), FIXTURE)
    const reloaded = await page.evaluate(file => window.__nadocTest.nanoparticles.conjugation.loadDesign(file), FIXTURE)
    expect(reloaded.design.nanoparticle_connection_versions).toHaveLength(2)
    expect(reloaded.design.nanoparticle_connection_versions.filter(version => version.applied)).toHaveLength(1)
    expect(reloaded.design.nanoparticle_connection_versions.find(version => version.applied).direct_variant).toBe(selectedVariant)
    const persistedAfterReload = await page.evaluate(({ strandId, overhangId }) => {
      const state = window.__nadocTest.store.getState()
      const cluster = state.currentDesign.cluster_transforms.find(
        item => item.overhang_duplex_driver_id === overhangId)
      const beads = state.currentGeometry
        .filter(item => item.strand_id === strandId || item.overhang_id === overhangId)
        .map(item => ({ strand_id: item.strand_id, bp_index: item.bp_index,
          backbone_position: item.backbone_position }))
      return { cluster, beads }
    }, { strandId: handle.strand_id, overhangId: overhang.id })
    expect(persistedAfterReload.cluster).toEqual(persistedBeforeSave.cluster)
    expect(persistedAfterReload.beads).toEqual(persistedBeforeSave.beads)
  })
})
