export async function demoReview(page, label) {
  if (process.env.NADOC_VR_DEMO !== '1') return
  console.log(`Review: ${label}`)
  await page.bringToFront()
  await page.waitForTimeout(Number(process.env.NADOC_VR_DEMO_HOLD || 6)*1000)
}
