import { expect, test } from '@playwright/test'

test('admin can demonstrate a contained demand-poisoning attack', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /enter shared workspace/i }).click()
  await expect(page.getByRole('heading', { name: 'Sentinel Industrial Demo' })).toBeVisible()
  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('button', { name: /Demand poisoning/ }).click()
  await expect(page.getByText('Compromised input was blocked before forecasting or approval.')).toBeVisible()
})

test('admin creates a supply chain with individual stages and a handoff', async ({ page }) => {
  const stamp = Date.now()
  await page.goto('/')
  await page.getByRole('button', { name: /enter shared workspace/i }).click()
  await expect(page.getByRole('heading', { name: 'Sentinel Industrial Demo' })).toBeVisible()

  await page.getByRole('button', { name: 'Supply chains' }).click()
  await expect(page.getByRole('heading', { name: 'Supply chains' })).toBeVisible()

  await page.getByRole('button', { name: /New supply chain/i }).click()
  await page.getByPlaceholder('east-assembly').fill(`qa-chain-${stamp}`)
  await page.getByPlaceholder('East assembly line').fill(`QA chain ${stamp}`)
  await page.getByRole('button', { name: 'Create chain' }).click()

  await expect(page.getByText('No stages in this chain')).toBeVisible()

  await page.getByRole('button', { name: /Add stage/i }).click()
  await page.getByPlaceholder('cold-storage').fill(`intake-${stamp}`)
  await page.getByPlaceholder('Cold storage').fill(`Raw intake ${stamp}`)
  await page.getByRole('button', { name: 'Create stage' }).click()

  await page.getByRole('button', { name: /Add stage/i }).click()
  await page.getByPlaceholder('cold-storage').fill(`assembly-${stamp}`)
  await page.getByPlaceholder('Cold storage').fill(`Assembly ${stamp}`)
  await page.getByRole('button', { name: 'Create stage' }).click()

  await expect(page.locator('.process-node', { hasText: `Raw intake ${stamp}` })).toBeVisible()
  await expect(page.locator('.process-node', { hasText: `Assembly ${stamp}` })).toBeVisible()

  await page.getByRole('button', { name: /Connect stages/i }).click()
  await expect(page.getByText('Pick the first stage to connect')).toBeVisible()
  await page.locator('.process-node', { hasText: `Raw intake ${stamp}` }).click()
  await expect(page.getByText('Now pick the target stage')).toBeVisible()
  await page.locator('.process-node', { hasText: `Assembly ${stamp}` }).click()

  await page.getByRole('button', { name: /Handoffs/i }).click()
  await expect(page.getByText('1 connections')).toBeVisible()
  await expect(page.getByText(`Raw intake ${stamp}`, { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: /Handoffs/i }).click()

  await page.getByRole('button', { name: /Add stage/i }).click()
  await page.getByPlaceholder('cold-storage').fill(`packing-${stamp}`)
  await page.getByPlaceholder('Cold storage').fill(`Packing ${stamp}`)
  await page.getByRole('button', { name: 'Create stage' }).click()
  await expect(page.locator('.process-node', { hasText: `Packing ${stamp}` })).toBeVisible()
  await page.locator('.topology-wrap').scrollIntoViewIfNeeded()

  const intake = page.locator('.process-node', { hasText: `Raw intake ${stamp}` })
  const packing = page.locator('.process-node', { hasText: `Packing ${stamp}` })
  const sourceHandle = await intake.locator('.react-flow__handle-right').boundingBox()
  const targetHandle = await packing.locator('.react-flow__handle-left').boundingBox()
  if (!sourceHandle || !targetHandle) throw new Error('node handles not visible')
  await page.mouse.move(sourceHandle.x + sourceHandle.width / 2, sourceHandle.y + sourceHandle.height / 2)
  await page.mouse.down()
  await page.mouse.move(targetHandle.x + targetHandle.width / 2, targetHandle.y + targetHandle.height / 2, { steps: 14 })
  await page.mouse.up()
  await expect(page.locator('.react-flow__edge')).toHaveCount(2)

  const edgeBox = await page.locator('.react-flow__edge').first().locator('.react-flow__edge-interaction').boundingBox()
  if (!edgeBox) throw new Error('edge not visible')
  await page.mouse.click(edgeBox.x + edgeBox.width / 2, edgeBox.y + edgeBox.height / 2)
  await page.keyboard.press('Delete')
  await expect(page.locator('.react-flow__edge')).toHaveCount(1)

  await page.getByRole('button', { name: /Handoffs/i }).click()
  await expect(page.getByText('1 connections')).toBeVisible()
})
