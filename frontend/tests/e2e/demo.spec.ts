import { expect, test } from '@playwright/test'

test('admin can demonstrate a contained demand-poisoning attack', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /enter control tower/i }).click()
  await expect(page.getByRole('heading', { name: 'Supply chain overview' })).toBeVisible()
  await page.getByRole('button', { name: 'Security lab' }).click()
  await page.getByRole('button', { name: /Demand poisoning/ }).click()
  await expect(page.getByText('Compromised input was blocked before forecasting or approval.')).toBeVisible()
})

