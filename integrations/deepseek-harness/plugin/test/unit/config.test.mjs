import { test } from 'node:test'
import assert from 'node:assert/strict'
import { homedir } from 'node:os'
import { join } from 'node:path'

import {
  DATA_DIR_NAME,
  DEFAULT_MAX_TOKENS,
  DEFAULT_TIMEOUT_MS,
  MAX_TOKENS_LIMIT,
  MIN_MAX_TOKENS,
  TOOL_IDS,
  TOOL_KEYS,
  isToolEnabled,
  resolveConfig,
  resolveMaxTokens,
} from '../../lib/config.js'

test('defaults match docs/SPEC.md §4 and §13', () => {
  const cfg = resolveConfig({}, { env: {} })
  assert.deepEqual(cfg.maxTokens, { ...DEFAULT_MAX_TOKENS })
  assert.equal(cfg.timeoutMs, DEFAULT_TIMEOUT_MS)
  assert.equal(cfg.indexMaxFileBytes, 1_048_576)
  assert.equal(cfg.promptSection, true)
  assert.equal(cfg.pythonPath, null)
  assert.equal(cfg.corePath, null)
  assert.ok(cfg.dataDir.endsWith(DATA_DIR_NAME), `dataDir should end with ${DATA_DIR_NAME}: ${cfg.dataDir}`)
  for (const key of TOOL_KEYS) assert.equal(cfg.tools[key], true)
  assert.deepEqual(cfg.errors, [])
  assert.equal(TOOL_KEYS.length, 6)
  assert.deepEqual(Object.keys(TOOL_IDS).sort(), [...TOOL_KEYS].sort())
})

test('a malformed row degrades to defaults without throwing', () => {
  for (const row of [null, undefined, 'nope', 42, [], true]) {
    const cfg = resolveConfig(row, { env: {} })
    assert.deepEqual(cfg.maxTokens, { ...DEFAULT_MAX_TOKENS })
    assert.equal(cfg.promptSection, true)
    assert.deepEqual(cfg.tools, Object.fromEntries(TOOL_KEYS.map((key) => [key, true])))
  }
})

test('row values override defaults and are clamped', () => {
  const cfg = resolveConfig(
    {
      maxTokens: { overview: 500, map: 999_999, search: 1, dependencies: 'not-a-number', context: 2200, impact: 1200 },
      pythonPath: ' C:/tools/python.exe ',
      corePath: ' C:/repo/src ',
      dataDir: ' C:/state/cbi ',
      timeoutMs: 5_000,
      indexMaxFileBytes: 4_194_304,
      tools: { map: false, impact: false },
      promptSection: false,
    },
    { env: {} },
  )
  assert.equal(cfg.maxTokens.overview, 500)
  assert.equal(cfg.maxTokens.map, MAX_TOKENS_LIMIT)
  assert.equal(cfg.maxTokens.search, MIN_MAX_TOKENS)
  assert.equal(cfg.maxTokens.dependencies, DEFAULT_MAX_TOKENS.dependencies)
  assert.equal(cfg.pythonPath, 'C:/tools/python.exe')
  assert.equal(cfg.corePath, 'C:/repo/src')
  assert.equal(cfg.dataDir, 'C:/state/cbi')
  assert.equal(cfg.timeoutMs, 5_000)
  assert.equal(cfg.indexMaxFileBytes, 4_194_304)
  assert.equal(isToolEnabled(cfg, 'map'), false)
  assert.equal(isToolEnabled(cfg, 'impact'), false)
  assert.equal(isToolEnabled(cfg, 'overview'), true)
  assert.equal(cfg.promptSection, false)
  assert.ok(cfg.errors.some((message) => message.includes('maxTokens.dependencies')))
})

test('timeout and file-size bounds are enforced', () => {
  const tooSmall = resolveConfig({ timeoutMs: 1, indexMaxFileBytes: 1 }, { env: {} })
  assert.equal(tooSmall.timeoutMs, 5_000)
  assert.equal(tooSmall.indexMaxFileBytes, 1_024)
  const tooLarge = resolveConfig({ timeoutMs: 10_000_000, indexMaxFileBytes: 10_000_000_000 }, { env: {} })
  assert.equal(tooLarge.timeoutMs, 600_000)
  assert.equal(tooLarge.indexMaxFileBytes, 64 * 1_048_576)
})

test('dataDir defaults under the Harness home', () => {
  const cfg = resolveConfig({}, { env: {} })
  assert.equal(cfg.dataDir, join(homedir(), '.dsh', DATA_DIR_NAME))
  const isolated = resolveConfig({}, { env: { DSH_HOME: 'F:/tmp/dsh-home' } })
  assert.equal(isolated.dataDir, join('F:/tmp/dsh-home', DATA_DIR_NAME))
  const explicit = resolveConfig({ dataDir: 'F:/state/cbi' }, { env: { DSH_HOME: 'F:/tmp/dsh-home' } })
  assert.equal(explicit.dataDir, 'F:/state/cbi')
})

test('resolveMaxTokens clamps to the documented range and falls back per tool', () => {
  const cfg = resolveConfig({ maxTokens: { search: 1300 } }, { env: {} })
  assert.equal(resolveMaxTokens(cfg, 'search', undefined), 1300)
  assert.equal(resolveMaxTokens(cfg, 'search', 999_999), MAX_TOKENS_LIMIT)
  assert.equal(resolveMaxTokens(cfg, 'search', 1), MIN_MAX_TOKENS)
  assert.equal(resolveMaxTokens(cfg, 'search', 1500.9), 1500)
  assert.equal(resolveMaxTokens(cfg, 'search', '1750'), 1750)
  assert.equal(resolveMaxTokens(cfg, 'search', 'nope'), 1300)
  assert.equal(resolveMaxTokens(cfg, 'overview', null), DEFAULT_MAX_TOKENS.overview)
  assert.equal(resolveMaxTokens({}, 'impact', 300), 300)
})
