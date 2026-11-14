import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

// Load the real composable through Vite's TS/alias pipeline; replace only HTTP.
let server, chat, requests
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const history = (text, extra = {}) => Response.json({ messages: [{ role: 'human', content: text }], ...extra })
before(async () => {
  server = await createServer({
    configFile: false,
    server: { middlewareMode: true, hmr: false, ws: false },
    optimizeDeps: { noDiscovery: true, include: [] },
    resolve: { alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) } },
    plugins: [{
      name: 'chat-http-fixture', enforce: 'pre',
      resolveId(id) { if (id.endsWith('/composables/useAuth')) return '\0chat-auth' },
      load(id) { if (id === '\0chat-auth') return 'export const useAuth = () => ({ authFetch: (...args) => globalThis.__chatFetch(...args) })' },
    }],
  })
  chat = (await server.ssrLoadModule('/src/composables/useChat.ts')).useChat()
})
beforeEach(() => {
  requests = []
  globalThis.__chatFetch = (url, options) => {
    if (url.endsWith('/sessions')) return Promise.resolve(Response.json({ sessions: [] }))
    const request = { url, options, ...deferred() }
    requests.push(request)
    return request.promise // Deliberately ignore abort: late responses must still be fenced.
  }
  chat.createNewSession()
})
after(async () => { await server?.close(); delete globalThis.__chatFetch })

test('B history wins when A arrives last', async () => {
  const a = chat.selectSession('A'), b = chat.selectSession('B')
  assert.equal(requests[0].options.signal.aborted, true)
  requests[1].resolve(history('B history'))
  await b
  requests[0].resolve(history('A history', { status: 'pending_confirmation', pending_action: { action_id: 'old' } }))
  await a
  assert.equal(chat.activeSessionId.value, 'B')
  assert.deepEqual(chat.messages.value.map(m => m.content), ['B history'])
  assert.equal(chat.pendingAction.value, null)
})

test('old failure cannot clear the loading flag or set an error on B', async () => {
  const a = chat.selectSession('A'), b = chat.selectSession('B')
  requests[0].reject(new Error('late failure'))
  await a
  assert.equal(chat.isLoadingHistory.value, true)
  assert.equal(chat.error.value, null)
  await chat.sendMessage('must wait for B')
  assert.equal(requests.length, 2)
  requests[1].resolve(history('B'))
  await b
  assert.equal(chat.isLoadingHistory.value, false)
})

test('changing chat while response.json is pending ignores the old body', async () => {
  const body = deferred()
  const a = chat.selectSession('A')
  requests[0].resolve({ ok: true, json: () => body.promise })
  await Promise.resolve()
  chat.createNewSession()
  body.resolve({ messages: [{ role: 'human', content: 'A' }] })
  await a
  assert.deepEqual(chat.messages.value, [])
  assert.equal(chat.isLoadingHistory.value, false)
})

for (const fails of [false, true]) {
  test(`confirmation for A ${fails ? 'failing' : 'completing'} after switching to B stays out of B`, async () => {
    const a = chat.selectSession('A')
    requests[0].resolve(history('A', { status: 'pending_confirmation', pending_action: {
      session_id: 'A', action_id: 'action-A', revision: 1, tool: 'create_meals',
    } }))
    await a
    const confirmation = chat.confirmAction('approve')
    const b = chat.selectSession('B')
    requests[2].resolve(history('B'))
    await b
    if (fails) requests[1].reject(new Error('old confirmation failed'))
    else requests[1].resolve(Response.json({ status: 'completed', reply: 'A was saved', run_id: 'run-A' }))
    await confirmation
    assert.deepEqual(chat.messages.value.map(m => m.content), ['B'])
    assert.equal(chat.error.value, null)
    assert.equal(chat.pendingAction.value, null)
    assert.equal(chat.isConfirming.value, false)
  })
}
