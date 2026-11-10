import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'

import { createService, normalizeRepoPath, workspaceStamp } from '../../lib/service.js'
import { fakeAgent, fakeBridge, fakeWorkspace, okPayload, tempDir, testConfig } from './_helpers.mjs'

function setup(t, { result = null, cfgOverrides = {} } = {}) {
  const scratch = tempDir(t, 'cbi-service')
  const repo = fakeWorkspace(t)
  const agent = fakeAgent({ cwd: repo })
  const cfg = testConfig(scratch, cfgOverrides)
  const bridge = fakeBridge(result)
  const service = createService({ cfg, bridge })
  return { scratch, repo, agent, cfg, bridge, service }
}

test('resolveWorkspaceRoot prefers session header cwd, then config cwd, then agent cwd', (t) => {
  const scratch = tempDir(t, 'cbi-service')
  const headerDir = join(scratch, 'header')
  const configDir = join(scratch, 'config')
  const agentDir = join(scratch, 'agent')
  for (const directory of [headerDir, configDir, agentDir]) mkdirSync(directory)
  const service = createService({ cfg: testConfig(scratch), bridge: fakeBridge() })
  assert.deepEqual(service.resolveWorkspaceRoot(fakeAgent({ cwd: agentDir })), { ok: true, root: agentDir })
  assert.deepEqual(service.resolveWorkspaceRoot(fakeAgent({ cwd: agentDir, header: { cwd: headerDir } })), { ok: true, root: headerDir })
  assert.deepEqual(
    service.resolveWorkspaceRoot({ id: 'a2', session: { header: { config: { cwd: configDir } } } }),
    { ok: true, root: configDir },
  )
  assert.deepEqual(service.resolveWorkspaceRoot({ id: 'a3', session: { header: {} }, cwd: agentDir }), { ok: true, root: agentDir })
  assert.deepEqual(service.resolveWorkspaceRoot(null), { ok: true, root: resolve(process.cwd()) })
})

test('workspace resolution rejects a missing or non-directory session cwd', () => {
  const service = createService({ cfg: testConfig(process.cwd()), bridge: fakeBridge() })
  const missing = service.resolveWorkspaceRoot(fakeAgent({ cwd: join(process.cwd(), 'does-not-exist-xyz') }))
  assert.equal(missing.ok, false)
  assert.match(missing.message, /does not exist/)
  assert.equal(JSON.stringify(missing).includes(process.cwd().slice(0, 3)), false)
})

test('calls validate required arguments before spawning the engine', async (t) => {
  const { service, agent, bridge } = setup(t)
  const cases = [
    ['search', {}, 'query'],
    ['context', {}, 'task'],
    ['dependencies', {}, 'target'],
    ['impact', {}, 'at least one file'],
    ['overview', { maxTokens: 900 }, null],
    ['nope', {}, 'unknown tool'],
  ]
  for (const [toolKey, args, hint] of cases) {
    if (hint === null) continue
    const result = await service.call(toolKey, args, { agent })
    assert.equal(result.ok, false, `${toolKey} should fail validation`)
    assert.equal(result.code, 'invalid_args', `${toolKey} should report invalid_args`)
    assert.ok(result.message.includes(hint), `${toolKey}: ${result.message}`)
  }
  assert.equal(bridge.calls.length, 0)
  // A valid overview call does reach the bridge.
  await service.call('overview', { maxTokens: 900 }, { agent })
  assert.equal(bridge.calls.length, 1)
})

test('path-like arguments are rejected when they escape the workspace', async (t) => {
  const { service, agent, bridge } = setup(t)
  const escaped = [
    ['map', { focus: '../outside' }],
    ['map', { focus: 'C:\\Windows' }],
    ['context', { task: 'x', pathPrefix: '/etc/passwd' }],
    ['dependencies', { target: '..\\secret.py' }],
    ['impact', { files: ['/etc/passwd'] }],
    ['impact', { symbols: ['C:\\Windows\\win.ini'] }],
  ]
  for (const [toolKey, args] of escaped) {
    const result = await service.call(toolKey, args, { agent })
    assert.equal(result.ok, false, `${toolKey} should reject ${JSON.stringify(args)}`)
    assert.equal(result.code, 'workspace_boundary', `${toolKey} should report workspace_boundary`)
    assert.equal(typeof result.repair.action, 'string')
  }
  assert.equal(bridge.calls.length, 0)
})

test('successful calls pass resolved arguments and budget to the bridge', async (t) => {
  const payload = okPayload('map')
  const { service, agent, bridge, repo, cfg } = setup(t, { result: () => ({ ok: true, payload }) })

  const result = await service.call('map', { focus: 'src\\app\\', maxTokens: 999_999 }, { agent })
  assert.deepEqual(result, payload)
  assert.equal(JSON.stringify(result), JSON.stringify(payload))
  assert.equal(bridge.calls.length, 1)
  const { toolKey, request } = bridge.calls[0]
  assert.equal(toolKey, 'map')
  assert.equal(request.root, resolve(repo))
  assert.equal(request.root.startsWith(cfg.dataDir), false)
  assert.ok(request.cacheDir.startsWith(join(cfg.dataDir, 'indexes')), 'cache dir must live under the plugin data dir')
  assert.equal(request.cacheDir.includes(repo), false)
  assert.equal(request.maxTokens, 8000)
  assert.deepEqual(request.args, { focus: 'src/app' })
  assert.equal(request.signal, null)
})

test('per-tool default and clamped budgets follow docs/SPEC.md §4', async (t) => {
  const { service, agent, bridge } = setup(t)
  await service.call('overview', {}, { agent })
  await service.call('search', { query: 'x', maxTokens: 1 }, { agent })
  await service.call('context', { task: 'x' }, { agent })
  assert.equal(bridge.calls[0].request.maxTokens, 900)
  assert.equal(bridge.calls[1].request.maxTokens, 200)
  assert.equal(bridge.calls[2].request.maxTokens, 2200)
})

test('row config can raise a per-tool default budget', async (t) => {
  const { service, agent, bridge } = setup(t, { cfgOverrides: { maxTokens: { search: 1500 } } })
  await service.call('search', { query: 'parse' }, { agent })
  assert.equal(bridge.calls[0].request.maxTokens, 1500)
})

test('dependencies and impact normalize their arguments deterministically', async (t) => {
  const { service, agent, bridge } = setup(t)
  await service.call('dependencies', { target: 'src\\app.py', direction: 'imports', depth: 3, refresh: true }, { agent })
  const first = bridge.calls[0].request
  assert.deepEqual(first.args, { refresh: true, target: 'src/app.py', direction: 'imports', depth: 3 })

  await service.call(
    'impact',
    { files: ['app.py', 'app.py', 'lib/util.py'], symbols: ['sym:app.py#function:main@1', 'main'] },
    { agent },
  )
  assert.deepEqual(bridge.calls[1].request.args, {
    files: ['app.py', 'lib/util.py'],
    symbols: ['sym:app.py#function:main@1', 'main'],
  })
})

test('memoized payloads are reused byte-identically until the workspace changes', async (t) => {
  const { service, agent, bridge, repo } = setup(t)
  const first = await service.call('overview', {}, { agent })
  const firstBytes = JSON.stringify(first)
  assert.equal(bridge.calls.length, 1)

  const second = await service.call('overview', {}, { agent })
  assert.equal(bridge.calls.length, 1, 'identical call must be served from the memo')
  assert.equal(JSON.stringify(second), firstBytes)
  assert.equal(JSON.stringify(second).includes('cache'), false)

  // A workspace change must invalidate the memo even though the args are identical.
  writeFileSync(join(repo, 'new_module.py'), 'VALUE = 1\n', 'utf8')
  const third = await service.call('overview', {}, { agent })
  assert.equal(bridge.calls.length, 2)
  assert.equal(JSON.stringify(third).includes('fingerprint-2'), true)

  // refresh always bypasses the memo and replaces the cached payload.
  await service.call('overview', { refresh: true }, { agent })
  assert.equal(bridge.calls.length, 3)
  const afterRefresh = await service.call('overview', { refresh: true }, { agent })
  assert.equal(bridge.calls.length, 4)
  const cached = await service.call('overview', {}, { agent })
  assert.equal(JSON.stringify(cached).includes('fingerprint-4'), true)
  assert.equal(JSON.stringify(afterRefresh).includes('fingerprint-4'), true)
})

test('memo entries are keyed by tool and arguments', async (t) => {
  const { service, agent, bridge } = setup(t)
  await service.call('overview', {}, { agent })
  await service.call('search', { query: 'alpha' }, { agent })
  await service.call('search', { query: 'beta' }, { agent })
  await service.call('search', { query: 'alpha' }, { agent })
  assert.equal(bridge.calls.length, 3)
})

test('invalidate() clears the memo and the interpreter probe', async (t) => {
  const { service, agent, bridge } = setup(t)
  await service.call('overview', {}, { agent })
  await service.call('overview', {}, { agent })
  assert.equal(bridge.calls.length, 1)
  service.invalidate()
  assert.equal(bridge.invalidated, 1)
  await service.call('overview', {}, { agent })
  assert.equal(bridge.calls.length, 2)
})

test('engine failures become the shared never-throw envelope', async (t) => {
  const failure = {
    ok: false,
    code: 'repo_error',
    message: 'the fixture repository is not indexable',
    repair: { action: 'check-workspace', label: 'Check the workspace', detail: 'Retry after fixing it.' },
  }
  const { service, agent } = setup(t, { result: () => failure })
  const result = await service.call('overview', {}, { agent })
  assert.deepEqual(result, failure)
})

test('an invalid engine payload and a throwing bridge never reject', async (t) => {
  const invalid = setup(t, { result: () => ({ ok: true, payload: 'not-an-object' }) })
  const invalidResult = await invalid.service.call('overview', {}, { agent: invalid.agent })
  assert.equal(invalidResult.code, 'engine_invalid_json')

  const throwing = setup(t, {
    result: () => {
      throw new Error('boom F:/secret/path')
    },
  })
  const thrownResult = await throwing.service.call('overview', {}, { agent: throwing.agent })
  assert.equal(thrownResult.ok, false)
  assert.equal(thrownResult.code, 'failed')
  assert.equal(JSON.stringify(thrownResult).includes('F:/secret/path'), false)
  assert.equal(typeof thrownResult.repair.action, 'string')
})

test('a workspace that disappears is reported without spawning the engine', async (t) => {
  const scratch = tempDir(t, 'cbi-service')
  const repo = fakeWorkspace(t)
  const bridge = fakeBridge()
  const service = createService({ cfg: testConfig(scratch), bridge })
  const agent = fakeAgent({ cwd: join(repo, 'missing-child') })
  const result = await service.call('overview', {}, { agent })
  assert.equal(result.ok, false)
  assert.equal(result.code, 'workspace_unavailable')
  assert.equal(bridge.calls.length, 0)
})

test('normalizeRepoPath accepts POSIX and Windows spellings, rejects escapes', () => {
  assert.deepEqual(normalizeRepoPath('src\\app.py'), { ok: true, value: 'src/app.py' })
  assert.deepEqual(normalizeRepoPath('./src//app.py'), { ok: true, value: 'src/app.py' })
  assert.deepEqual(normalizeRepoPath('src'), { ok: true, value: 'src' })
  for (const bad of ['', '   ', '..', '../x', '/etc', 'C:\\x', '~/.ssh', 'src/../../x']) {
    assert.equal(normalizeRepoPath(bad).ok, false, `should reject ${JSON.stringify(bad)}`)
  }
})

test('workspaceStamp is deterministic and changes with filesystem state', (t) => {
  const repo = fakeWorkspace(t)
  const first = workspaceStamp(repo)
  assert.match(first, /^[0-9a-f]{16}$/)
  assert.equal(workspaceStamp(repo), first)
  writeFileSync(join(repo, 'second.py'), 'X = 2\n', 'utf8')
  const second = workspaceStamp(repo)
  assert.notEqual(second, first)
  assert.equal(workspaceStamp(repo), second)
  // Backslashes in `relative()` must not leak into the stamp on Windows.
  assert.equal(first.includes(sep), false)
})
