import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'

import {
  buildEngineArgs,
  createBridge,
  ENGINE_MODULE,
  parseEngineStdout,
  pythonPathFor,
  repairFor,
} from '../../lib/bridge.js'
import { DEFAULT_MAX_FILE_BYTES } from '../../lib/config.js'
import { fakeEngine, fakeWorkspace, tempDir, testConfig } from './_helpers.mjs'

const ROOT = 'F:/work/repo'
const CACHE = 'F:/state/cbi/indexes/abc123'

test('buildEngineArgs pins the CLI contract for all six commands', () => {
  const cfg = { indexMaxFileBytes: DEFAULT_MAX_FILE_BYTES }
  const shared = ['--json', '--root', ROOT, '--cache-dir', CACHE]

  assert.deepEqual(buildEngineArgs({ toolKey: 'overview', root: ROOT, cacheDir: CACHE, cfg, args: {}, maxTokens: 900 }), [
    'overview',
    ...shared,
    '--max-tokens',
    '900',
    '--max-file-bytes',
    '1048576',
  ])

  assert.deepEqual(
    buildEngineArgs({ toolKey: 'map', root: ROOT, cacheDir: CACHE, cfg, args: { focus: 'src/app' }, maxTokens: 1600 }),
    ['map', ...shared, '--max-tokens', '1600', '--max-file-bytes', '1048576', '--focus', 'src/app'],
  )

  assert.deepEqual(
    buildEngineArgs({ toolKey: 'search', root: ROOT, cacheDir: CACHE, cfg, args: { query: 'parse_file' }, maxTokens: 1200 }),
    ['search', ...shared, '--max-tokens', '1200', '--max-file-bytes', '1048576', '--query', 'parse_file'],
  )

  assert.deepEqual(
    buildEngineArgs({
      toolKey: 'dependencies',
      root: ROOT,
      cacheDir: CACHE,
      cfg,
      args: { target: 'src/app.py', direction: 'imports', depth: 3 },
      maxTokens: 1200,
    }),
    [
      'dependencies',
      ...shared,
      '--max-tokens',
      '1200',
      '--max-file-bytes',
      '1048576',
      '--target',
      'src/app.py',
      '--direction',
      'imports',
      '--depth',
      '3',
    ],
  )

  assert.deepEqual(
    buildEngineArgs({
      toolKey: 'context',
      root: ROOT,
      cacheDir: CACHE,
      cfg,
      args: { task: 'find the parser', pathPrefix: 'src/codebase_intelligence' },
      maxTokens: 2200,
    }),
    [
      'context',
      ...shared,
      '--max-tokens',
      '2200',
      '--max-file-bytes',
      '1048576',
      '--task',
      'find the parser',
      '--path-prefix',
      'src/codebase_intelligence',
    ],
  )

  assert.deepEqual(
    buildEngineArgs({
      toolKey: 'impact',
      root: ROOT,
      cacheDir: CACHE,
      cfg,
      args: { files: ['a.py', 'b.py'], symbols: ['sym:a.py#function:main@1'] },
      maxTokens: 1200,
    }),
    [
      'impact',
      ...shared,
      '--max-tokens',
      '1200',
      '--max-file-bytes',
      '1048576',
      '--files',
      'a.py,b.py',
      '--symbols',
      'sym:a.py#function:main@1',
    ],
  )
})

test('buildEngineArgs is deterministic and includes defaults explicitly', () => {
  const request = {
    toolKey: 'dependencies',
    root: ROOT,
    cacheDir: CACHE,
    cfg: { indexMaxFileBytes: 4096 },
    args: { target: 'src/app.py' },
    maxTokens: 1200,
  }
  const first = buildEngineArgs(request)
  const second = buildEngineArgs({ ...request })
  assert.deepEqual(first, second)
  assert.deepEqual(first.slice(-6), ['--target', 'src/app.py', '--direction', 'both', '--depth', '1'])
})

test('buildEngineArgs adds --force only when refresh is requested', () => {
  const plain = buildEngineArgs({ toolKey: 'overview', root: ROOT, cacheDir: CACHE, cfg: {}, args: {}, maxTokens: 900 })
  const forced = buildEngineArgs({ toolKey: 'overview', root: ROOT, cacheDir: CACHE, cfg: {}, args: { refresh: true }, maxTokens: 900 })
  assert.equal(plain.includes('--force'), false)
  assert.equal(forced.includes('--force'), true)
  assert.throws(() => buildEngineArgs({ toolKey: 'nope', root: ROOT, cacheDir: CACHE, cfg: {}, maxTokens: 1 }), /unknown tool key/)
})

test('parseEngineStdout accepts exactly one canonical object and rejects everything else', () => {
  const payload = { ok: true, index: { fingerprint: 'fp' } }
  assert.deepEqual(parseEngineStdout(`${JSON.stringify(payload)}\n`), { ok: true, payload })
  assert.deepEqual(parseEngineStdout(`note on stdout\n${JSON.stringify(payload)}\n`), { ok: true, payload })

  const garbage = parseEngineStdout('this is not JSON\n')
  assert.equal(garbage.ok, false)
  assert.equal(garbage.code, 'engine_invalid_json')
  assert.equal(JSON.stringify(garbage).includes('this is not JSON'), false)

  const empty = parseEngineStdout('  \n')
  assert.equal(empty.code, 'engine_invalid_json')
  assert.match(empty.message, /no output/)

  const array = parseEngineStdout('[1,2,3]\n')
  assert.equal(array.code, 'engine_invalid_json')
})

test('repairFor yields path-free structured repair hints', () => {
  for (const code of ['engine_unavailable', 'engine_timeout', 'engine_invalid_json', 'invalid_args', 'not_found', 'repo_error', 'canceled', 'something_else']) {
    const repair = repairFor(code)
    assert.equal(typeof repair.action, 'string')
    assert.ok(repair.label.length > 10)
    assert.ok(repair.detail.length > 10)
    assert.equal(/[A-Za-z]:\\/.test(repair.detail), false)
  }
})

test('pythonPathFor prefers CBI_PYTHONPATH, then the core source dir, then inherited', () => {
  const cfg = { corePath: 'F:/no-such-core' }
  const env = { CBI_PYTHONPATH: `F:/fake-engine${delimiter}F:/extra`, PYTHONPATH: 'F:/inherited' }
  assert.equal(pythonPathFor(cfg, env), `F:/fake-engine${delimiter}F:/extra${delimiter}F:/inherited`)
  // Duplicates are removed (case-insensitively on Windows).
  const envDuplicate = { CBI_PYTHONPATH: 'F:/fake', PYTHONPATH: 'F:/fake' }
  assert.equal(pythonPathFor(cfg, envDuplicate), 'F:/fake')
})

test('run() spawns the fake engine and returns its payload verbatim', async (t) => {
  const engine = fakeEngine(t)
  const scratch = tempDir(t, 'cbi-bridge')
  const repo = fakeWorkspace(t)
  const cfg = testConfig(scratch)
  const bridge = createBridge({ cfg })
  const cacheDir = `${scratch}/indexes/x`

  const result = await bridge.run('overview', { root: repo, cacheDir, maxTokens: 900 })
  assert.equal(result.ok, true)
  assert.equal(result.payload.ok, true)
  assert.equal(result.payload.command, 'overview')
  assert.equal(result.payload.index.fingerprint, 'fingerprint-fixture')

  const calls = engine.calls()
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0], [
    'overview',
    '--json',
    '--root',
    repo,
    '--cache-dir',
    cacheDir,
    '--max-tokens',
    '900',
    '--max-file-bytes',
    '1048576',
  ])
  assert.equal(result.payload.command, calls[0][0])
})

test('run() maps the engine error envelope to the plugin envelope', async (t) => {
  const engine = fakeEngine(t)
  engine.mode('error')
  const scratch = tempDir(t, 'cbi-bridge')
  const repo = fakeWorkspace(t)
  const bridge = createBridge({ cfg: testConfig(scratch) })

  const result = await bridge.run('search', { root: repo, cacheDir: `${scratch}/indexes/x`, maxTokens: 1200, args: { query: 'x' } })
  assert.equal(result.ok, false)
  assert.equal(result.code, 'repo_error')
  assert.equal(result.message, 'the fixture repository is not indexable')
  assert.equal(typeof result.repair.action, 'string')
  assert.equal(JSON.stringify(result).includes(repo), false)
})

test('run() rejects invalid JSON without leaking engine stdout', async (t) => {
  const engine = fakeEngine(t)
  engine.mode('invalid')
  const scratch = tempDir(t, 'cbi-bridge')
  const repo = fakeWorkspace(t)
  const bridge = createBridge({ cfg: testConfig(scratch) })

  const result = await bridge.run('map', { root: repo, cacheDir: `${scratch}/indexes/x`, maxTokens: 1600 })
  assert.equal(result.ok, false)
  assert.equal(result.code, 'engine_invalid_json')
  assert.equal(JSON.stringify(result).includes('this is not the JSON object'), false)
})

test('run() reports empty stdout as an invalid payload', async (t) => {
  const engine = fakeEngine(t)
  engine.mode('silent')
  const scratch = tempDir(t, 'cbi-bridge')
  const repo = fakeWorkspace(t)
  const bridge = createBridge({ cfg: testConfig(scratch) })

  const result = await bridge.run('overview', { root: repo, cacheDir: `${scratch}/indexes/x`, maxTokens: 900 })
  assert.equal(result.code, 'engine_invalid_json')
  assert.match(result.message, /no output/)
})

test('run() enforces the timeout and kills the child', async (t) => {
  const engine = fakeEngine(t)
  engine.mode('timeout')
  const scratch = tempDir(t, 'cbi-bridge')
  const repo = fakeWorkspace(t)
  const cfg = testConfig(scratch, { timeoutMs: 5_000 })
  const bridge = createBridge({ cfg: { ...cfg, timeoutMs: 500 } })
  const startedAt = Date.now()

  const result = await bridge.run('overview', { root: repo, cacheDir: `${scratch}/indexes/x`, maxTokens: 900, args: {} })
  const elapsed = Date.now() - startedAt
  assert.equal(result.ok, false)
  assert.equal(result.code, 'engine_timeout')
  assert.ok(elapsed < 15_000, `timeout took too long: ${elapsed}ms`)
})

test('run() reports engine_unavailable when no interpreter candidate exists', async (t) => {
  const scratch = tempDir(t, 'cbi-bridge')
  const repo = fakeWorkspace(t)
  const bridge = createBridge({ cfg: testConfig(scratch), candidates: [] })
  const result = await bridge.run('overview', { root: repo, cacheDir: `${scratch}/indexes/x`, maxTokens: 900 })
  assert.equal(result.ok, false)
  assert.equal(result.code, 'engine_unavailable')
  assert.match(result.message, /Python 3\.11\+/)
  assert.equal(JSON.stringify(result).includes('python.exe'), false)
})

test('createBridge caches the probe and invalidate() re-probes', async (t) => {
  const engine = fakeEngine(t)
  const scratch = tempDir(t, 'cbi-bridge')
  const repo = fakeWorkspace(t)
  const bridge = createBridge({ cfg: testConfig(scratch) })
  assert.equal(bridge.candidates().length > 0, true)

  const first = await bridge.probe()
  const second = await bridge.probe()
  assert.equal(first.ready, true)
  assert.equal(first, second)
  bridge.invalidate()
  const third = await bridge.probe()
  assert.equal(third.ready, true)
  assert.equal(third.label, first.label)
  assert.equal(engine.calls().length, 0)
  // The bridge is created with a real interpreter and yields the module name it runs.
  assert.equal(ENGINE_MODULE, 'codebase_intelligence.cli')
})


test('tool and export execution do not resolve Python modules from the workspace', async (t) => {
  const engine = fakeEngine(t)
  const repo = fakeWorkspace(t)
  const shadow = join(repo, 'codebase_intelligence')
  mkdirSync(shadow)
  writeFileSync(join(shadow, '__init__.py'), '')
  writeFileSync(join(shadow, 'cli.py'), 'print(\'{"ok":true,"fixture_marker":true}\')')
  const bridge = createBridge({ cfg: testConfig(tempDir(t, 'cbi-shadow')) })
  const tool = await bridge.run('overview', { root: repo })
  const exported = await bridge.runRaw({ command: 'export', root: repo, args: ['--check'] })
  assert.equal(tool.payload.command, 'overview')
  assert.equal(exported.payload.command, 'export')
  assert.deepEqual(engine.calls().map((args) => args[0]), ['overview', 'export'])
})
