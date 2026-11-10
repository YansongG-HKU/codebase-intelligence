/**
 * Host panel route tests (PANEL_CONTRACT.md §3): gate, routing, dispatch,
 * export confirmation and git facts. Uses fake services — no engine required.
 */
import assert from 'node:assert/strict'
import { execFileSync, execSync } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { dirname, join, resolve } from 'node:path'

import {
  ROUTES,
  checkRequestGate,
  dispatch,
  gitFacts,
  handleRequest,
  matchRoute,
  readJsonBody,
  statusForCode,
} from '../../lib/panel.js'

import { tempDir } from './_helpers.mjs'

const HEADER = 'x-dsh-codebase-intelligence'
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', '..')

function fakeRes() {
  const state = { status: 0, headers: null, body: '', headersSent: false, writableEnded: false }
  return {
    state,
    writeHead(status, headers) {
      state.status = status
      state.headers = headers
      state.headersSent = true
    },
    end(body) {
      state.body = typeof body === 'string' ? body : String(body ?? '')
      state.writableEnded = true
    },
  }
}

function fakeReq({ method = 'GET', url = '/dsh-codebase-intelligence/api/state', headers = {}, body = null } = {}) {
  const chunks = body === null ? [] : [Buffer.from(JSON.stringify(body), 'utf8')]
  return {
    method,
    url,
    headers: { host: '127.0.0.1:3098', [HEADER]: '1', ...headers },
    async *[Symbol.asyncIterator]() {
      for (const chunk of chunks) yield chunk
    },
  }
}

function fakeService(overrides = {}) {
  const calls = []
  const base = {
    cfg: { exportDir: 'docs/codebase-intelligence' },
    bridge: { probe: async () => ({ ready: true, version: [3, 13, 0] }) },
    resolveSessionRoot: (sessionId) => (sessionId === 'missing' ? null : '/tmp/workspace'),
    panelCall: async (toolKey, args, options) => {
      calls.push({ toolKey, args, options })
      return { ok: true, command: toolKey, index: { fingerprint: 'fp' }, budgets: { tokensEstimated: 10, maxTokens: 100 } }
    },
    exportPreview: async () => ({
      ok: true,
      payload: {
        outDir: 'docs/codebase-intelligence',
        files: [
          { path: 'docs/codebase-intelligence/overview.json', status: 'unchanged', bytes: 10 },
          { path: 'docs/codebase-intelligence/REPO_MAP.md', status: 'created', bytes: 20 },
        ],
        stale: true,
        manifestFingerprint: 'mf',
      },
    }),
    exportWrite: async () => ({
      ok: true,
      payload: {
        outDir: 'docs/codebase-intelligence',
        files: [{ path: 'docs/codebase-intelligence/overview.json', status: 'updated', bytes: 11 }],
        manifestFingerprint: 'mf2',
      },
    }),
  }
  return { service: { ...base, ...overrides }, calls }
}

test('gate rejects missing marker, non-loopback host and mismatched origin', () => {
  const webServer = { port: 3098, protocol: 'http:' }
  assert.equal(checkRequestGate(webServer, { headers: { host: '127.0.0.1:3098' } }).ok, false)
  assert.equal(
    checkRequestGate(webServer, { headers: { host: 'example.com', [HEADER]: '1' } }).ok,
    false,
  )
  assert.equal(
    checkRequestGate(webServer, { headers: { host: '127.0.0.1:3098', [HEADER]: '1', origin: 'http://127.0.0.1:9999' } }).ok,
    false,
  )
  assert.equal(
    checkRequestGate(webServer, { headers: { host: '127.0.0.1:3098', [HEADER]: '1', origin: 'http://127.0.0.1:3098' } }).ok,
    true,
  )
  assert.equal(
    checkRequestGate(webServer, { headers: { host: 'localhost:3098', [HEADER]: '1' } }).ok,
    true,
  )
})

test('route table covers every contract route', () => {
  const paths = [
    '/dsh-codebase-intelligence/api/state',
    '/dsh-codebase-intelligence/api/overview',
    '/dsh-codebase-intelligence/api/map',
    '/dsh-codebase-intelligence/api/search',
    '/dsh-codebase-intelligence/api/dependencies',
    '/dsh-codebase-intelligence/api/context',
    '/dsh-codebase-intelligence/api/impact',
    '/dsh-codebase-intelligence/api/export',
    '/dsh-codebase-intelligence/api/git',
  ]
  for (const path of paths) assert.ok(matchRoute(path), `missing route ${path}`)
  assert.equal(matchRoute('/dsh-codebase-intelligence/api/nope'), null)
  for (const descriptor of ROUTES) assert.ok(descriptor.methods.length > 0)
  assert.equal(statusForCode('invalid_arguments'), 400)
  assert.equal(statusForCode('workspace_unavailable'), 503)
  assert.equal(statusForCode('engine_timeout'), 504)
})

test('handleRequest returns JSON 200 / 403 / 404 / 405', async () => {
  const { service } = fakeService()
  const webCtx = { webServer: { port: 3098, protocol: 'http:' } }

  const denied = fakeRes()
  await handleRequest(webCtx, service, fakeReq({ headers: { [HEADER]: undefined } }), denied)
  assert.equal(denied.state.status, 403)

  const missing = fakeRes()
  await handleRequest(webCtx, service, fakeReq({ url: '/dsh-codebase-intelligence/api/nope' }), missing)
  assert.equal(missing.state.status, 404)

  const wrongMethod = fakeRes()
  await handleRequest(
    webCtx,
    service,
    fakeReq({ method: 'DELETE', url: '/dsh-codebase-intelligence/api/state' }),
    wrongMethod,
  )
  assert.equal(wrongMethod.state.status, 405)

  const ok = fakeRes()
  await handleRequest(webCtx, service, fakeReq({}), ok)
  assert.equal(ok.state.status, 200)
  const payload = JSON.parse(ok.state.body)
  assert.equal(payload.ok, true)
  assert.equal(payload.data.root, '/tmp/workspace')
  assert.equal(payload.data.engine.available, true)
  assert.equal(payload.data.git.available, false)
  assert.equal(payload.data.git.command, null)
})

test('state reports workspace_unavailable without a live session root', async () => {
  const { service } = fakeService({ resolveSessionRoot: () => null })
  const result = await dispatch({
    service,
    url: new URL('http://127.0.0.1:3098/dsh-codebase-intelligence/api/state?session=missing'),
    descriptor: matchRoute('/dsh-codebase-intelligence/api/state'),
    method: 'GET',
    body: {},
  })
  assert.equal(result.ok, false)
  assert.equal(result.code, 'workspace_unavailable')
})

test('tool routes pass session, budgets and arguments to the service', async () => {
  const { service, calls } = fakeService()
  const cases = [
    ['overview?maxTokens=500', 'overview', 500],
    ['map?maxTokens=700&focus=src', 'map', 700],
    ['search?maxTokens=400&query=token', 'search', 400],
    ['context?maxTokens=900&task=find+parser', 'context', 900],
    ['impact?maxTokens=300&files=a.py,b.py', 'impact', 300],
  ]
  for (const [query, toolKey, budget] of cases) {
    const result = await dispatch({
      service,
      url: new URL(`http://127.0.0.1:3098/dsh-codebase-intelligence/api/${query}&session=s1`),
      descriptor: matchRoute(`/dsh-codebase-intelligence/api/${query.split('?')[0]}`),
      method: 'GET',
      body: {},
    })
    assert.equal(result.ok, true)
    assert.equal(result.data.command, toolKey)
    const call = calls.at(-1)
    assert.equal(call.toolKey, toolKey)
    assert.equal(call.args.maxTokens, budget)
    assert.equal(call.options.sessionId, 's1')
  }
  const impactCall = calls.at(-1)
  assert.deepEqual(impactCall.args.files, ['a.py', 'b.py'])
})

test('budgets are clamped to the documented range', async () => {
  const { service, calls } = fakeService()
  for (const [requested, expected] of [
    ['10', 200],
    ['999999', 8000],
    ['1200', 1200],
  ]) {
    await dispatch({
      service,
      url: new URL(`http://127.0.0.1:3098/dsh-codebase-intelligence/api/overview?maxTokens=${requested}`),
      descriptor: matchRoute('/dsh-codebase-intelligence/api/overview'),
      method: 'GET',
      body: {},
    })
    assert.equal(calls.at(-1).args.maxTokens, expected)
  }
})

test('export preview and write: confirm is required and git facts are attached', async () => {
  const { service, calls } = fakeService()
  const preview = await dispatch({
    service,
    url: new URL('http://127.0.0.1:3098/dsh-codebase-intelligence/api/export?session=s1'),
    descriptor: matchRoute('/dsh-codebase-intelligence/api/export'),
    method: 'GET',
    body: {},
  })
  assert.equal(preview.ok, true)
  assert.equal(preview.data.stale, true)
  assert.equal(preview.data.files.length, 2)
  assert.equal(preview.data.git.command, null)

  const denied = await dispatch({
    service,
    url: new URL('http://127.0.0.1:3098/dsh-codebase-intelligence/api/export'),
    descriptor: matchRoute('/dsh-codebase-intelligence/api/export'),
    method: 'POST',
    body: {},
  })
  assert.equal(denied.ok, false)
  assert.equal(denied.code, 'invalid_arguments')
  assert.equal(calls.length, 0)

  let exported = null
  const written = await dispatch({
    service,
    url: new URL('http://127.0.0.1:3098/dsh-codebase-intelligence/api/export'),
    descriptor: matchRoute('/dsh-codebase-intelligence/api/export'),
    method: 'POST',
    body: { session: 's1', confirm: true },
    options: { onExported: (data) => (exported = data) },
  })
  assert.equal(written.ok, true)
  assert.equal(written.data.files[0].status, 'updated')
  assert.equal(exported.outDir, 'docs/codebase-intelligence')
})

test('readJsonBody rejects invalid JSON and oversize bodies', async () => {
  const invalid = fakeReq({ method: 'POST', body: null })
  invalid[Symbol.asyncIterator] = async function* () {
    yield Buffer.from('{not json}', 'utf8')
  }
  await assert.rejects(() => readJsonBody(invalid), /valid JSON/u)

  const big = fakeReq({ method: 'POST', body: null })
  big[Symbol.asyncIterator] = async function* () {
    yield Buffer.alloc(1024)
  }
  await assert.rejects(() => readJsonBody(big, 16), /exceeds/u)
})

test('POST body.session is a fallback when the query has no session', async () => {
  const { service, calls } = fakeService()
  const result = await dispatch({
    service,
    url: new URL('http://127.0.0.1:3098/dsh-codebase-intelligence/api/refresh'),
    descriptor: matchRoute('/dsh-codebase-intelligence/api/refresh'),
    method: 'POST',
    body: { session: 's-body' },
  })
  assert.equal(result.ok, true)
  assert.equal(calls.at(-1).toolKey, 'overview')
  assert.equal(calls.at(-1).args.refresh, true)
  assert.equal(calls.at(-1).options.sessionId, 's-body')
})

test('gitFacts is read-only and yields the suggested command', async () => {
  const facts = await gitFacts(REPO_ROOT, 'docs/codebase-intelligence')
  assert.equal(typeof facts.command, 'string')
  assert.ok(facts.command.startsWith('git add -- docs/codebase-intelligence'))
  assert.equal(typeof facts.available, 'boolean')
  assert.ok(Array.isArray(facts.exportChanges))
  assert.ok(facts.exportChanges.length <= 50)
})


test('git facts support unborn HEAD without running repository hooks', async (t) => {
  const root = tempDir(t, 'cbi-git-facts')
  const git = (...args) => execFileSync('git', args, { cwd: root, stdio: 'pipe' })
  git('init', '-q', '-b', 'main')
  const hook = join(root, 'fixture-hook.sh')
  writeFileSync(hook, '#!/bin/sh\nprintf called > marker.txt\nexit 1\n', { mode: 0o755 })
  git('config', 'core.fsmonitor', hook.replaceAll('\\', '/'))
  const facts = await gitFacts(root, 'docs/codebase-intelligence')
  assert.equal(facts.available, true)
  assert.equal(facts.branch, 'main')
  assert.equal(existsSync(join(root, 'marker.txt')), false)
  assert.match(facts.command, /git commit --only .* -- docs\/codebase-intelligence/)
  const unusual = await gitFacts(root, 'docs/unsafe & preview')
  assert.equal(unusual.available, true)
  assert.equal(unusual.command, null)
})


test('git facts identify detached HEAD and the suggested commit excludes unrelated staged files', async (t) => {
  const root = tempDir(t, 'cbi-git-commit')
  const git = (...args) => execFileSync('git', args, { cwd: root, stdio: 'pipe', encoding: 'utf8' }).trim()
  git('init', '-q', '-b', 'main')
  git('config', 'user.name', 'Fixture')
  git('config', 'user.email', 'fixture@example.invalid')
  git('config', 'commit.gpgsign', 'false')
  git('config', 'core.hooksPath', join(root, 'no-hooks'))
  writeFileSync(join(root, 'outside.txt'), 'original')
  git('add', '--', 'outside.txt')
  git('commit', '-qm', 'initial')
  git('checkout', '--detach', '-q')
  writeFileSync(join(root, 'outside.txt'), 'unrelated staged edit')
  git('add', '--', 'outside.txt')
  mkdirSync(join(root, 'docs', 'codebase-intelligence'), { recursive: true })
  writeFileSync(join(root, 'docs', 'codebase-intelligence', 'overview.json'), '{}')
  const facts = await gitFacts(root, 'docs/codebase-intelligence')
  assert.equal(facts.available, true)
  assert.equal(facts.branch, git('rev-parse', '--short', 'HEAD'))
  assert.equal(facts.dirty, true)
  execSync(facts.command, { cwd: root, stdio: 'pipe' })
  assert.equal(git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'), 'docs/codebase-intelligence/overview.json')
  assert.equal(git('diff', '--cached', '--name-only'), 'outside.txt')
})


test('graph endpoint forwards its session and preserves structured stale errors', async () => {
  const calls = []
  const service = { async panelGraph(query, options) {
    calls.push({ query, options })
    return query.source ? { ok: false, code: 'stale_graph' } : { ok: true, payload: { nodes: [] } }
  } }
  const request = (params, method = 'GET', body = {}) => dispatch({
    service, url: new URL('http://localhost/dsh-codebase-intelligence/api/graph?' + params),
    descriptor: matchRoute('/dsh-codebase-intelligence/api/graph'), method, body,
  })
  assert.deepEqual(await request('session=s1&focus=dir%3Aapp&offset=0'), { ok: true, data: { nodes: [] } })
  assert.equal(calls[0].options.sessionId, 's1')
  assert.equal(calls[0].query.focus, 'dir:app')
  assert.equal((await request('session=s1&source=app%2Fmain.py&line=1')).code, 'stale_graph')
  await request('refresh=1', 'GET', { session: 's1' })
  assert.equal(calls[2].options.refresh, undefined)
  await request('source=ignored', 'POST', { session: 's1' })
  assert.deepEqual(calls[3], { query: {}, options: { sessionId: 's1', refresh: true } })
  assert.equal(statusForCode('stale_graph'), 409)
})
