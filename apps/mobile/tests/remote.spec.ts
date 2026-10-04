import { test, expect } from '@playwright/test'

test.beforeEach(async ({ request }) => {
  await request.post('http://127.0.0.1:8792/fixture/control', {
    data: { user: 'alice', online: true, expired: false, deleted: false }
  })
})

test('signed login, latest history, full output, older pagination and stale approval at 360px', async ({
  page,
  request
}) => {
  await page.goto('/')
  await page.getByRole('link', { name: /安全登录/ }).click()
  await page.getByRole('button', { name: /alice long conversation/ }).click()
  await expect(page.getByText('alice newest message')).toBeVisible()
  await expect(page.getByText('alice history 1', { exact: true })).toHaveCount(0)
  await page.getByText('长文本 · 展开完整内容').click()
  await expect(page.getByText(/END OF LONG OUTPUT/)).toBeVisible()
  await page.getByRole('button', { name: /加载更早消息/ }).click()
  await page.getByRole('button', { name: /加载更早消息/ }).click()
  await expect(page.getByText('alice history 1', { exact: true })).toBeVisible()
  await request.post('http://127.0.0.1:8792/fixture/control', { data: { expired: true, deleted: true } })
  await expect(page.getByText('请求已过期，请等待电脑上的新请求。')).toBeVisible()
  await expect(page.getByRole('button', { name: '允许一次' })).toBeDisabled()
  await expect(page.getByText('alice newest message')).toHaveCount(0)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  expect(overflow).toBe(false)
})

test('offline draft remains local, reconnect repairs, uncertain POST checks its real receipt', async ({
  page,
  context,
  request
}) => {
  await page.goto('/')
  await page.getByRole('link', { name: /安全登录/ }).click()
  await page.getByRole('button', { name: /alice long conversation/ }).click()
  await expect(page.getByText('电脑已连接', { exact: true })).toBeVisible()
  await context.setOffline(true)
  await page.getByRole('textbox', { name: '消息草稿' }).fill('offline private draft')
  await expect(page.getByRole('button', { name: '继续会话', exact: true })).toBeDisabled()
  const before = (await (await request.get('http://127.0.0.1:8792/fixture/state')).json()).commands.length
  await context.setOffline(false)
  await expect(page.getByText('实时连接', { exact: true })).toBeVisible()
  expect((await (await request.get('http://127.0.0.1:8792/fixture/state')).json()).commands.length).toBe(before)
  await page.route(
    '**/api/remote/sessions/*/commands',
    async route => {
      await route.fetch()
      await route.abort('connectionreset')
    },
    { times: 1 }
  )
  await page.getByRole('button', { name: '继续会话', exact: true }).click()
  await expect(page.getByText(/发送结果待核对|执行端已接受/)).toBeVisible()
  await page.getByRole('button', { name: '查询回执' }).click()
  await expect(page.getByText(/执行端已接受/)).toBeVisible()
  await expect(page.getByRole('textbox', { name: '消息草稿' })).toHaveValue('')
  expect((await (await request.get('http://127.0.0.1:8792/fixture/state')).json()).commands.length).toBe(before + 1)
})

test('logout clears account drafts and new signed identity cannot see previous history', async ({ page, request }) => {
  await page.goto('/')
  await page.getByRole('link', { name: /安全登录/ }).click()
  await page.getByRole('button', { name: /alice long conversation/ }).click()
  await page.getByRole('textbox', { name: '消息草稿' }).fill('alice secret draft')
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.getByRole('link', { name: /安全登录/ })).toBeVisible()
  expect(
    await page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('hermes.remote.v1:')))
  ).toEqual([])
  await request.post('http://127.0.0.1:8792/fixture/control', { data: { user: 'bob' } })
  await page.getByRole('link', { name: /安全登录/ }).click()
  await page.getByRole('button', { name: /bob long conversation/ }).click()
  await expect(page.getByRole('textbox', { name: '消息草稿' })).toHaveValue('')
  await expect(page.getByText('alice newest message')).toHaveCount(0)
  await expect(page.getByText('bob newest message')).toBeVisible()
})

test('pairing survives OIDC root callback and sources require explicit consent', async ({ page, request }) => {
  const response = await request.post('/api/remote/pairings', {
    data: {
      name: 'Explicit consent PC',
      sources: [{ backend_id: 'separate-source', engine: 'hermes', profile: 'new' }]
    }
  })
  const pairing = await response.json()
  await page.goto(`/pair?pairing_id=${pairing.pairing_id}`)
  await page.getByRole('link', { name: /安全登录/ }).click()
  await expect(page.getByRole('heading', { name: '选择要共享的来源' })).toBeVisible()
  await expect(page.getByRole('checkbox')).not.toBeChecked()
  await expect(page.getByRole('button', { name: '授权 0 个来源' })).toBeDisabled()
  await page.getByRole('checkbox').check()
  await page.getByPlaceholder('输入配对码').fill(pairing.user_code)
  await page.getByRole('button', { name: '授权 1 个来源' }).click()
  await expect(page.getByRole('heading', { name: '授权已确认' })).toBeVisible()
})
