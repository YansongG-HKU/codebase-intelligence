/**
 * Shared fixtures for the dsh-codebase-intelligence unit suite.
 *
 * No network, no real engine, no writes outside `os.tmpdir()`: every test gets a
 * disposable directory removed afterwards, and the "engine" is a tiny fake
 * Python package (`codebase_intelligence/cli.py`) placed first on `PYTHONPATH`
 * through `CBI_PYTHONPATH`, so the bridge's real spawn/probe/parse path is
 * exercised without any repository parsing.
 */

import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

import { resolveConfig } from '../../lib/config.js'

/** Create a unique temp directory, removed when the test finishes. */
export function tempDir(t, label = 'cbi-plugin-test') {
  const dir = mkdtempSync(join(tmpdir(), `${label}-`))
  t.after(() => {
    try {
      rmSync(dir, { recursive: true, force: true })
    } catch {
      /* best effort */
    }
  })
  return dir
}

/** Write a file, creating parent directories. */
export function writeFixtureFile(path, content) {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, content, 'utf8')
}

/**
 * Script of the fake engine module. It records its argv when configured and
 * switches behaviour with `CBI_FAKE_MODE`; its payloads are intentionally small
 * but shape-compatible with the real reporting payloads (index/budgets/ok).
 */
const FAKE_CLI = `"""Fake codebase_intelligence engine CLI used by plugin unit tests."""

import json
import os
import sys
import time


def _emit(payload):
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\\n")


def main(argv):
    calls = os.environ.get("CBI_FAKE_CALLS")
    if calls:
        with open(calls, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(list(argv)) + "\\n")
    mode = os.environ.get("CBI_FAKE_MODE", "success")
    if mode == "timeout":
        time.sleep(30)
        return 0
    if mode == "invalid":
        sys.stdout.write("this is not the JSON object the contract promises\\n")
        return 0
    if mode == "silent":
        return 0
    if mode == "error":
        _emit({"ok": False, "error": {"code": "repo_error", "message": "the fixture repository is not indexable"}, "schemaVersion": "1"})
        return 3
    command = argv[0] if argv else "overview"
    _emit({
        "ok": True,
        "schemaVersion": "1",
        "command": command,
        "index": {
            "schemaVersion": "1",
            "engineVersion": "0.1.0",
            "policyFingerprint": "policy-fixture",
            "fingerprint": os.environ.get("CBI_FAKE_FINGERPRINT", "fingerprint-fixture"),
        },
        "budgets": {"maxTokens": 900, "tokensEstimated": 42, "tokenEstimator": "chars4-wide-v1"},
        "truncated": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
`

const SAVED_ENV_KEYS = ['CBI_PYTHONPATH', 'CBI_FAKE_MODE', 'CBI_FAKE_CALLS', 'CBI_FAKE_FINGERPRINT']

/**
 * Materialize the fake Python engine and point the bridge at it.
 *
 * @param {import('node:test').TestContext} t
 */
export function fakeEngine(t) {
  const root = tempDir(t, 'cbi-fake-engine')
  const pkg = join(root, 'codebase_intelligence')
  writeFixtureFile(join(pkg, '__init__.py'), '"""Fake package for plugin unit tests."""\n')
  writeFixtureFile(join(pkg, 'cli.py'), FAKE_CLI)
  const callsPath = join(root, 'calls.jsonl')

  const previous = new Map()
  for (const key of SAVED_ENV_KEYS) previous.set(key, process.env[key])
  process.env.CBI_PYTHONPATH = root
  process.env.CBI_FAKE_CALLS = callsPath
  delete process.env.CBI_FAKE_MODE
  delete process.env.CBI_FAKE_FINGERPRINT
  t.after(() => {
    for (const key of SAVED_ENV_KEYS) {
      const value = previous.get(key)
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  })

  return {
    root,
    callsPath,
    /** Switch the fake engine behaviour (`success`, `error`, `invalid`, `timeout`, `silent`). */
    mode(value) {
      if (value === undefined) delete process.env.CBI_FAKE_MODE
      else process.env.CBI_FAKE_MODE = value
    },
    /** Override the fake `index.fingerprint`. */
    fingerprint(value) {
      if (value === undefined) delete process.env.CBI_FAKE_FINGERPRINT
      else process.env.CBI_FAKE_FINGERPRINT = value
    },
    /** Parsed argv rows recorded by the fake engine. */
    calls() {
      try {
        return readFileSync(callsPath, 'utf8')
          .split(/\r?\n/u)
          .filter((line) => line.trim().length > 0)
          .map((line) => JSON.parse(line))
      } catch {
        return []
      }
    },
    reset() {
      try {
        rmSync(callsPath, { force: true })
      } catch {
        /* first call, nothing recorded yet */
      }
    },
  }
}

/**
 * A plugin config resolved from a row without depending on the host machine,
 * with `corePath` pointed at a non-package directory so only `CBI_PYTHONPATH`
 * decides which `codebase_intelligence` package is imported.
 *
 * @param {string} scratchDir a temp directory for dataDir/cache
 * @param {object} [row] loader-row config overrides
 */
export function testConfig(scratchDir, row = {}) {
  return resolveConfig(
    {
      corePath: join(scratchDir, 'no-such-core'),
      dataDir: join(scratchDir, 'data'),
      timeoutMs: 20_000,
      ...row,
    },
    { env: {} },
  )
}

/** A resolved config with plugin defaults only (no machine paths). */
export function defaultConfig() {
  return resolveConfig({}, { env: {} })
}

/** Fake live Agent exposing the pieces the plugin touches. */
export function fakeAgent({ id = 'agent-1', cwd = 'C:/work', header = {}, noTools = false, noSystemPrompt = false } = {}) {
  const registrations = []
  const sections = []
  const agent = {
    id,
    session: { id, header: { cwd, ...header } },
    ctx: {},
  }
  if (!noTools) {
    agent.ctx.tools = {
      register(definition) {
        registrations.push(definition)
        return () => {
          const index = registrations.indexOf(definition)
          if (index >= 0) registrations.splice(index, 1)
        }
      },
    }
  }
  if (!noSystemPrompt) {
    agent.ctx.systemPrompt = {
      section(definition) {
        sections.push(definition)
        return () => {
          const index = sections.indexOf(definition)
          if (index >= 0) sections.splice(index, 1)
        }
      },
    }
  }
  agent.__test = { registrations, sections }
  return agent
}

/** Fake plugin host ctx for `apply` tests. */
export function fakeHost(agents = []) {
  const listeners = new Map()
  return {
    ctx: {
      agents: { list: () => agents },
      logger: { info() {}, warn() {} },
      on(event, listener) {
        const list = listeners.get(event) ?? []
        list.push(listener)
        listeners.set(event, list)
        return () => {
          const index = list.indexOf(listener)
          if (index >= 0) list.splice(index, 1)
        }
      },
    },
    emit(event, payload) {
      for (const listener of listeners.get(event) ?? []) listener(payload)
    },
    listeners,
  }
}

/** Fake service for tool-definition tests. */
export function fakeToolService(handler = null) {
  const calls = []
  return {
    calls,
    async call(toolKey, args, options) {
      calls.push({ toolKey, args, options })
      if (typeof handler === 'function') return handler(toolKey, args, options)
      return { ok: true, command: toolKey, args }
    },
  }
}

/** A minimal success payload shaped like a reporting payload. */
export function okPayload(command = 'overview', fingerprint = 'fingerprint-fixture') {
  return {
    ok: true,
    schemaVersion: '1',
    command,
    index: { schemaVersion: '1', engineVersion: '0.1.0', policyFingerprint: 'policy-fixture', fingerprint },
    budgets: { maxTokens: 900, tokensEstimated: 42, tokenEstimator: 'chars4-wide-v1' },
    truncated: false,
  }
}

/** Fake bridge for service tests (records calls, returns a payload factory result). */
export function fakeBridge(result = null) {
  const calls = []
  return {
    calls,
    invalidated: 0,
    async run(toolKey, request) {
      calls.push({ toolKey, request })
      if (typeof result === 'function') return result(toolKey, request)
      if (result !== null) return result
      return { ok: true, payload: okPayload(toolKey, `fingerprint-${calls.length}`) }
    },
    invalidate() {
      this.invalidated += 1
    },
  }
}

/** A disposable fake workspace directory on disk. */
export function fakeWorkspace(t, files = { 'app.py': 'def main():\n    return 0\n' }) {
  const root = tempDir(t, 'cbi-workspace')
  for (const [relative, content] of Object.entries(files)) writeFixtureFile(join(root, relative), content)
  return root
}
