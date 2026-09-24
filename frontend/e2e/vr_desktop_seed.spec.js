import { test } from '@playwright/test'
import { paintDesktopVRSeed } from './helpers/vr_desktop_seed.js'

test('desktop mouse extrusion creates the canonical six-helix VR seed', async ({page}, testInfo) => {
  await page.goto('/?doc=__e2e__vr-desktop-seed')
  await page.locator('.menu-item').filter({hasText:'File'}).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name','__e2e__VR desktop gesture seed')
  await page.getByRole('button',{name:'Create',exact:true}).click()
  await paintDesktopVRSeed(page,testInfo)
})
