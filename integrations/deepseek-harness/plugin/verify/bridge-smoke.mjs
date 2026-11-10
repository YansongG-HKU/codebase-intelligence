#!/usr/bin/env node
/**
 * Live bridge smoke test for `dsh-codebase-intelligence`.
 *
 * Unlike `test/unit/*.test.mjs` (which pin the plugin against a fake engine),
 * this script runs the **real** Python engine through the plugin's bridge on the
 * fixture repository (`tests/fixtures/plugin/demo_repo/`). It is the integration
 * gate the Lead runs once `python -m codebase_intelligence.cli overview --json`
 * works; it never modifies the fixture and writes its index cache to a
 * disposable temp directory.
 *
 * Usage (bundled Node or any Node >= 22):
 *   node verify/bridge-smoke.mjs            # fixture repo
 *   node verify/bridge-smoke.mjs --root <path>
 *
 * Prints ONE JSON object:
 *   {ok, root, python, checks:{...}, tools:[{tool, ok, code?, bytes, tokens?, truncated?, fingerprint?}], errors:[...]}
 * Exit codes: 0 pass, 1 failed check, 2 engine unavailable.
 */

import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { createBridge } from '../lib/bridge.js'
import { resolveConfig } from '../lib/config.js'
import { createService } from '../lib/service.js'
import { resolveCorePath } from '../lib/paths.js'

const HARNESS_DIR = dirname(fileURLToPath(import.meta.url))
const PLUGIN_DIR = resolve(HARNESS_DIR, '..')
const REPO_DIR = resolve(PLUGIN_DIR, '..', '..', '..')

function argValue(argv, flag) {
  const index = argv.indexOf(flag)
  return index >= 0 && index + 1 < argv.length ? argv[index + 1] : null
}

const root = resolve(argValue(process.argv.slice(2), '--root') ?? join(REPO_DIR, 'tests', 'fixtures', 'plugin', 'demo_repo'))
const scratch = mkdtempSync(join(tmpdir(), 'cbi-bridge-smoke-'))
const cfg = resolveConfig(
  { dataDir: scratch, timeoutMs: 120_000, indexMaxFileBytes: 1_048_576 },
  { env: process.env },
)
const agent = { id: 'bridge-smoke', session: { header: { cwd: root } } }
const log = { info() {}, warn() {} }
const bridge = createBridge({ cfg, log })
const service = createService({ cfg, log, bridge })

const checks = {}
const tools = []
const errors = []

function record(tool, result) {
  if (result && result.ok === true) {
    const bytes = Buffer.byteLength(JSON.stringify(result), 'utf8')
    tools.push({
      tool,
      ok: true,
      bytes,
      truncated: result.truncated === true,
      fingerprint: typeof result.index?.fingerprint === 'string' ? result.index.fingerprint.slice(0, 12) : null,
      tokens: result.budgets?.tokensEstimated ?? null,
    })
  } else {
    tools.push({ tool, ok: false, code: result?.code ?? 'unknown', message: result?.message ?? 'no result' })
    errors.push(`${tool}: ${result?.code ?? 'unknown'} ${result?.message ?? ''}`.trim())
  }
  return result
}

async function main() {
  const probe = await bridge.probe()
  if (!probe.ready) {
    process.stdout.write(`${JSON.stringify({ ok: false, root, python: null, engineUnavailable: true, checks: {}, tools, errors: [probe.error] }, null, 2)}\n`)
    return 2
  }
  checks.python = `${probe.label} (${probe.version.join('.')})`
  checks.corePath = resolveCorePath(cfg)
  checks.root = root

  const overview = record('codebase_overview', await service.call('overview', {}, { agent }))
  checks.overviewShape = Boolean(overview?.ok === true && overview.repo && overview.index?.fingerprint)
  checks.overviewRepo = overview?.repo ? { files: overview.repo.files, symbols: overview.repo.symbols, languages: overview.repo.languages?.length ?? 0 } : null

  const overviewAgain = await service.call('overview', {}, { agent })
  checks.deterministicRepeat = JSON.stringify(overviewAgain) === JSON.stringify(overview)

  const refreshed = record('codebase_overview(refresh)', await service.call('overview', { refresh: true }, { agent }))
  checks.refreshIdentical = JSON.stringify(refreshed) === JSON.stringify(overview)
  checks.fingerprintStable = refreshed?.index?.fingerprint === overview?.index?.fingerprint

  const map = record('codebase_map', await service.call('map', {}, { agent }))
  // Derive a real target from the repository instead of assuming one fixture layout.
  const targetPath =
    (typeof overview?.entryPoints?.[0]?.path === 'string' && overview.entryPoints[0].path) ||
    (typeof map?.entries?.[0]?.path === 'string' && map.entries[0].path) ||
    'app/services.py'
  const topDirectory = overview?.repo?.topDirectories?.[0]?.path
  checks.dependencyTarget = targetPath
  checks.pathPrefix = typeof topDirectory === 'string' ? topDirectory : null

  record('codebase_search', await service.call('search', { query: 'class' }, { agent }))
  record('codebase_dependencies', await service.call('dependencies', { target: targetPath, direction: 'dependents' }, { agent }))
  record(
    'codebase_context',
    await service.call(
      'context',
      { task: 'add a small helper function', ...(checks.pathPrefix === null ? {} : { pathPrefix: checks.pathPrefix }), maxTokens: 1200 },
      { agent },
    ),
  )
  record('codebase_impact', await service.call('impact', { files: [targetPath] }, { agent }))

  const boundary = await service.call('map', { focus: '../outside' }, { agent })
  checks.workspaceBoundary = boundary.ok === false && boundary.code === 'workspace_boundary'

  const invalid = await service.call('search', { query: '   ' }, { agent })
  checks.argumentValidation = invalid.ok === false && invalid.code === 'invalid_args'

  const toolFailures = tools.filter((entry) => entry.ok !== true)
  checks.allToolsOk = toolFailures.length === 0
  const ok = checks.allToolsOk && checks.overviewShape && checks.deterministicRepeat && checks.refreshIdentical && checks.workspaceBoundary && checks.argumentValidation

  process.stdout.write(
    `${JSON.stringify(
      {
        ok,
        root,
        python: { label: probe.label, version: probe.version.join('.'), command: probe.command },
        dataDir: scratch,
        checks,
        tools,
        errors,
      },
      null,
      2,
    )}\n`,
  )
  return ok ? 0 : 1
}

try {
  const exitCode = await main()
  process.exitCode = exitCode
} catch (error) {
  process.stdout.write(`${JSON.stringify({ ok: false, root, error: error instanceof Error ? error.message : String(error), checks, tools, errors }, null, 2)}\n`)
  process.exitCode = 1
} finally {
  try {
    service.invalidate()
    rmSync(scratch, { recursive: true, force: true })
  } catch {
    /* best effort */
  }
}
