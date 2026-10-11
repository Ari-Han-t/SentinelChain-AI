import { expect, test } from '@playwright/test'

test('reviews captured recommendations and personal incident notifications', async ({ page, request }, testInfo) => {
  const api = String(testInfo.project.metadata.apiURL)
  const login = await request.post(`${api}/auth/login`, { data: { email: 'admin@sentinelchain.local', password: 'demo1234' } })
  expect(login.ok()).toBeTruthy()
  const { access_token } = await login.json()
  const generated = await request.post(`${api}/nodes/2/guidance/refresh`, { headers: { Authorization: `Bearer ${access_token}` } })
  expect(generated.ok()).toBeTruthy()
  await page.goto('/')
  await page.getByRole('button', { name: 'Enter shared workspace', exact: true }).click()
  await page.getByRole('button', { name: 'Recommendations', exact: true }).click()
  await page.getByRole('button', { name: /Review stage recommendation/ }).first().click()
  await expect(page.getByRole('region', { name: 'Recommendation explanation' })).toContainText(/no calibrated/i)
  await page.getByRole('button', { name: /^Notifications/ }).click()
  await page.getByRole('button', { name: 'Check sources and deadlines', exact: true }).click()
  await expect(page.getByRole('button', { name: /Review incident/ }).first()).toBeVisible()
  const markRead = page.getByRole('button', { name: 'Mark read', exact: true }).first()
  if (await markRead.count()) {
    await markRead.click()
    await expect(page.getByRole('button', { name: 'Mark unread', exact: true }).first()).toBeVisible()
  }
})
