/**
 * Bridge to the Codebase Intelligence Python engine.
 *
 * The engine is a normal Python package invoked through one JSON-in/JSON-out
 * CLI (`python -m codebase_intelligence.cli <command> --json ...`). This module
 * owns:
 *
 * - interpreter discovery (config `pythonPath` → `CBI_PYTHON` → DSH managed
 *   runtimes → `python`/`python3`/`py -3` → common installs), gated by a probe
 *   that proves Python ≥ 3.11 and an importable `codebase_intelligence.cli`;
 * - the exact argv contract for the six tool commands (see docs/DSH_PLUGIN.md);
 * - UTF-8 stdio, a timeout, bounded capture and structured failures;
 * - mapping engine output/exit codes to the plugin's never-throw envelope.
 *
 * Nothing here parses repository content in JavaScript, and no payload text
 * reaches a model unless it is one canonical JSON object the engine printed.
 *
 * @module dsh-codebase-intelligence/bridge
 */

import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { delimiter, join } from 'node:path'

import { DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_TOKENS, DEFAULT_TIMEOUT_MS, TOOL_CLI_COMMAND } from './config.js'
import { PLUGIN_DIR, cacheDirFor, resolveCorePath } from './paths.js'
import { firstLine, isPlainObject, messageOf } from './util.js'

/** The module executed inside the Python interpreter. */
export const ENGINE_MODULE = 'codebase_intelligence.cli'

/** Minimum supported Python (the engine uses modern standard-library features). */
const MIN_PYTHON = Object.freeze([3, 11])

/** Interpreter probe budget. */
const PROBE_TIMEOUT_MS = 20_000

/** Maximum bytes captured per stream from one engine call. */
const MAX_CAPTURE_BYTES = 8 * 1024 * 1024

/** Code printed by the probe: proves the module imports and reports the version. */
const PROBE_SNIPPET =
  'import json, sys\n' +
  'import codebase_intelligence.cli\n' +
  'print(json.dumps({"version": list(sys.version_info[:3])}))\n'

/**
 * Build the ordered interpreter candidates.
 *
 * Path-like candidates are only kept when they exist, so a stale configured
 * path does not hide a working interpreter further down the list. Bare command
 * names (`python`, `python3`, `py`) resolve through `PATH` at spawn time.
 *
 * @param {{cfg?: object, env?: Record<string, string | undefined>, home?: string}} [options]
 * @returns {Array<{command: string, args: string[], label: string}>}
 */
export function candidateList({ cfg = {}, env = process.env, home = homedir() } = {}) {
  const list = []
  const seen = new Set()
  const add = (command, args = [], label = '') => {
    if (typeof command !== 'string' || command.trim().length === 0) return
    const key = `${command}\u0000${args.join('\u0000')}`
    if (seen.has(key)) return
    seen.add(key)
    if (command.includes('\\') || command.includes('/')) {
      if (!existsSync(command)) return
    }
    list.push({ command, args: [...args], label: label || [command, ...args].join(' ') })
  }

  add(cfg?.pythonPath, [], 'config.pythonPath')
  add(env.CBI_PYTHON, [], 'CBI_PYTHON')
  add(env.DSH_CBI_PYTHON, [], 'DSH_CBI_PYTHON')

  // DSH-managed Python runtimes (same layout the Python-based DSH plugins use).
  const dshHome = typeof env.DSH_HOME === 'string' && env.DSH_HOME.length > 0 ? env.DSH_HOME : join(home, '.dsh')
  const runtimesDir = join(dshHome, 'dsh-runtimes')
  try {
    for (const name of readdirSync(runtimesDir).sort()) {
      const base = join(runtimesDir, name, 'dependencies', 'python')
      add(join(base, 'python.exe'), [], `DSH runtime ${name}`)
      add(join(base, 'bin', 'python3'), [], `DSH runtime ${name}`)
    }
  } catch {
    /* no managed runtimes on this machine */
  }

  add('python', [], 'python')
  add('python3', [], 'python3')
  add('py', ['-3'], 'py -3')

  const localAppData =
    typeof env.LOCALAPPDATA === 'string' && env.LOCALAPPDATA.length > 0 ? env.LOCALAPPDATA : join(home, 'AppData', 'Local')
  for (const candidate of [
    join(home, 'miniconda3', 'python.exe'),
    join(home, 'anaconda3', 'python.exe'),
    join(home, 'miniconda3', 'envs', 'base', 'python.exe'),
    'C:\\ProgramData\\miniconda3\\python.exe',
    'C:\\ProgramData\\anaconda3\\python.exe',
    'C:\\Python313\\python.exe',
    'C:\\Python312\\python.exe',
    'C:\\Python311\\python.exe',
    join(localAppData, 'Programs', 'Python', 'Python313', 'python.exe'),
    join(localAppData, 'Programs', 'Python', 'Python312', 'python.exe'),
    '/usr/bin/python3',
    '/usr/local/bin/python3',
  ]) {
    add(candidate, [], 'common install')
  }
  return list
}

/**
 * `PYTHONPATH` value for the engine: extra test/dev paths, then the source
 * checkout's `src/` (unless `config.corePath` overrides it), then whatever the
 * host already had. Empty string means "leave `PYTHONPATH` alone" (the engine
 * is a pip-installed package).
 *
 * @param {{corePath?: string | null}} cfg resolved config
 * @param {Record<string, string | undefined>} [env]
 * @returns {string}
 */
export function pythonPathFor(cfg, env = process.env) {
  const entries = []
  const pushAll = (value) => {
    if (typeof value !== 'string' || value.length === 0) return
    for (const part of value.split(delimiter)) {
      if (part.trim().length > 0) entries.push(part.trim())
    }
  }
  pushAll(env.CBI_PYTHONPATH)
  const corePath = resolveCorePath(cfg)
  if (corePath !== null) entries.push(corePath)
  pushAll(env.PYTHONPATH)

  const seen = new Set()
  const unique = []
  for (const entry of entries) {
    const key = process.platform === 'win32' ? entry.toLowerCase() : entry
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(entry)
  }
  return unique.join(delimiter)
}

/**
 * Build the engine argv (after `-m codebase_intelligence.cli`) for one tool call.
 *
 * Exported because it is the integration point the CLI owner and the tests both
 * pin. Always explicit: root, cache directory, max tokens, max file bytes and
 * per-command args (direction/depth included at their defaults) so identical
 * plugin state produces identical argv.
 *
 * @param {{
 *   toolKey: string,
 *   root: string,
 *   cacheDir: string,
 *   cfg?: object,
 *   args?: Record<string, unknown>,
 *   maxTokens?: number,
 * }} request
 * @returns {string[]} CLI arguments
 */
export function buildEngineArgs({ toolKey, root, cacheDir, cfg = {}, args = {}, maxTokens }) {
  const command = TOOL_CLI_COMMAND[toolKey]
  if (typeof command !== 'string') throw new Error(`unknown tool key ${JSON.stringify(toolKey)}`)
  const argv = [command, '--json', '--root', String(root), '--cache-dir', String(cacheDir)]
  const budget = Number.isInteger(maxTokens) ? maxTokens : DEFAULT_MAX_TOKENS[toolKey] ?? 1200
  argv.push('--max-tokens', String(budget))
  if (args.refresh === true) argv.push('--force')
  const maxFileBytes = Number.isInteger(cfg.indexMaxFileBytes) ? cfg.indexMaxFileBytes : DEFAULT_MAX_FILE_BYTES
  argv.push('--max-file-bytes', String(maxFileBytes))

  switch (toolKey) {
    case 'map':
      if (typeof args.focus === 'string' && args.focus.length > 0) argv.push('--focus', args.focus)
      break
    case 'search':
      if (typeof args.query === 'string' && args.query.length > 0) argv.push('--query', args.query)
      break
    case 'dependencies':
      if (typeof args.target === 'string' && args.target.length > 0) argv.push('--target', args.target)
      argv.push('--direction', args.direction === 'imports' || args.direction === 'dependents' ? args.direction : 'both')
      argv.push('--depth', String(Number.isInteger(args.depth) ? args.depth : 1))
      break
    case 'context':
      if (typeof args.task === 'string' && args.task.length > 0) argv.push('--task', args.task)
      if (typeof args.pathPrefix === 'string' && args.pathPrefix.length > 0) argv.push('--path-prefix', args.pathPrefix)
      break
    case 'impact':
      if (Array.isArray(args.files) && args.files.length > 0) argv.push('--files', args.files.join(','))
      if (Array.isArray(args.symbols) && args.symbols.length > 0) argv.push('--symbols', args.symbols.join(','))
      break
    default:
      break
  }
  return argv
}

/**
 * Repair hints for structured failures. Kept path-free: an error envelope is
 * model-facing and must not leak machine paths (docs/SPEC.md §3).
 *
 * @param {string} code failure code
 * @returns {{action: string, label: string, detail: string}}
 */
export function repairFor(code) {
  switch (code) {
    case 'engine_unavailable':
      return {
        action: 'check-python',
        label: 'Install Python 3.11+ with the codebase_intelligence package, or set config.pythonPath',
        detail: 'Point config.pythonPath or the CBI_PYTHON environment variable at a Python 3.11+ interpreter that can import codebase_intelligence.cli, then retry.',
      }
    case 'engine_timeout':
      return {
        action: 'retry',
        label: 'Retry once; if it persists, lower maxTokens or refresh the index',
        detail: 'A cold first index of a large repository can exceed the timeout; a retry reuses the cached index.',
      }
    case 'engine_invalid_json':
      return {
        action: 'check-engine',
        label: 'Run the engine CLI once with --json and inspect stderr',
        detail: 'Run `python -m codebase_intelligence.cli overview --json --root <workspace>` in the same interpreter; stdout must be exactly one JSON object.',
      }
    case 'invalid_args':
    case 'invalid_arguments':
      return {
        action: 'fix-arguments',
        label: 'Fix the arguments and retry',
        detail: 'Check the required argument and its documented range; repository paths are POSIX and relative to the workspace root.',
      }
    case 'not_found':
      return {
        action: 'check-target',
        label: 'Use codebase_search or codebase_map to find a valid path or symbol id',
        detail: 'The requested file or symbol is not in the current index; search for it first, then retry.',
      }
    case 'repo_error':
      return {
        action: 'check-workspace',
        label: 'Check that the workspace is a readable repository',
        detail: 'The engine could not scan or index this workspace; check permissions and ignore rules, then retry.',
      }
    case 'canceled':
      return { action: 'retry', label: 'Retry the call', detail: 'The step was aborted before the engine finished.' }
    default:
      return {
        action: 'retry',
        label: 'Retry once; if it persists, call codebase_overview to check the workspace',
        detail: 'The engine returned a structured failure; the attempt made no changes.',
      }
  }
}

/**
 * Create one bridge instance for a resolved plugin config.
 *
 * The instance caches the interpreter probe (until `invalidate()`) and shares
 * no mutable state with other plugin instances. It never throws: `run()`
 * resolves to either `{ok: true, payload}` or the error envelope.
 *
 * @param {{
 *   cfg?: object,
 *   log?: {info?: Function, warn?: Function} | null,
 *   candidates?: Array<{command: string, args: string[], label: string}> | null,
 *   env?: Record<string, string | undefined>,
 * }} [options]
 */
export function createBridge({ cfg = {}, log = null, candidates = null, env = process.env } = {}) {
  let probePromise = null
  let probeKey = null

  const signature = () =>
    JSON.stringify({
      pythonPath: cfg.pythonPath ?? null,
      corePath: cfg.corePath ?? null,
      cbiPython: env.CBI_PYTHON ?? null,
      dshHome: env.DSH_HOME ?? null,
      candidates: candidates === null ? null : candidates.length,
    })

  /** Drop the cached probe (e.g. after the user installs Python or sets pythonPath). */
  function invalidate() {
    probePromise = null
    probeKey = null
  }

  /** Resolve and probe the interpreter once; same promise until invalidated. */
  function probe({ force = false } = {}) {
    const key = signature()
    if (!force && probePromise !== null && probeKey === key) return probePromise
    probeKey = key
    const list = candidates === null ? candidateList({ cfg, env }) : candidates
    probePromise = probeInterpreter(list)
    return probePromise
  }

  async function probeInterpreter(list) {
    const unavailable = 'no Python 3.11+ interpreter with the codebase_intelligence package was found'
    if (!Array.isArray(list) || list.length === 0) {
      return { ready: false, error: unavailable }
    }
    const pythonPath = pythonPathFor(cfg, env)
    const attempts = []
    for (const candidate of list) {
      const result = await runCapture(candidate.command, [...candidate.args, '-c', PROBE_SNIPPET], {
        cwd: PLUGIN_DIR,
        env: spawnEnv(pythonPath),
        timeoutMs: PROBE_TIMEOUT_MS,
      })
      if (result.timedOut) {
        attempts.push({ candidate: candidate.label, error: 'probe timed out' })
        continue
      }
      if (result.error) {
        attempts.push({ candidate: candidate.label, error: 'could not start the interpreter' })
        continue
      }
      if (result.exitCode !== 0) {
        attempts.push({ candidate: candidate.label, error: firstLine(result.stderr, 200) || `exit ${result.exitCode}` })
        continue
      }
      const info = parseLastJsonLine(result.stdout)
      const version = Array.isArray(info?.version) ? info.version.map((part) => Number(part)) : null
      if (!version || !Number.isInteger(version[0]) || version.length < 2) {
        attempts.push({ candidate: candidate.label, error: 'the probe did not report a Python version' })
        continue
      }
      if (version[0] < MIN_PYTHON[0] || (version[0] === MIN_PYTHON[0] && version[1] < MIN_PYTHON[1])) {
        attempts.push({ candidate: candidate.label, error: `Python ${version.join('.')} is older than 3.11` })
        continue
      }
      if (attempts.length > 0) {
        log?.warn?.(`skipped ${attempts.length} unusable interpreter candidate(s): ${summarizeAttempts(attempts)}`)
      }
      log?.info?.(`Python engine ready (${candidate.label}, Python ${version.join('.')})`)
      return { ready: true, command: candidate.command, args: [...candidate.args], label: candidate.label, version }
    }
    log?.warn?.(`no usable Python engine: ${summarizeAttempts(attempts)}`)
    return {
      ready: false,
      error: unavailable,
    }
  }

  /**
   * Run one tool command through the engine.
   *
   * @param {string} toolKey short tool key (`overview`, `map`, ...)
   * @param {{root: string, cacheDir?: string, maxTokens?: number, args?: object, signal?: AbortSignal}} request
   * @returns {Promise<{ok: true, payload: object} | {ok: false, code: string, message: string, repair: object}>}
   */
  async function run(toolKey, request = {}) {
    try {
      if (typeof TOOL_CLI_COMMAND[toolKey] !== 'string') {
        return failure('invalid_args', 'unknown tool command', repairFor('invalid_args'))
      }
      const root = typeof request.root === 'string' ? request.root : ''
      if (root.length === 0) return failure('workspace_unavailable', 'no workspace root was resolved', repairFor('failed'))
      if (request.signal?.aborted) return failure('canceled', 'the call was aborted before the engine started', repairFor('canceled'))

      const ready = await probe()
      if (!ready.ready) return failure('engine_unavailable', ready.error, repairFor('engine_unavailable'))

      const cacheDir = typeof request.cacheDir === 'string' && request.cacheDir.length > 0 ? request.cacheDir : cacheDirFor(cfg, root)
      try {
        mkdirSync(cacheDir, { recursive: true })
      } catch {
        log?.warn?.(`could not create the index cache directory ${cacheDir}`)
        return failure('engine_failed', 'the plugin could not prepare its index cache directory', repairFor('failed'))
      }

      const argv = buildEngineArgs({ toolKey, root, cacheDir, cfg, args: request.args ?? {}, maxTokens: request.maxTokens })
      const timeoutMs = Number.isInteger(cfg.timeoutMs) ? cfg.timeoutMs : DEFAULT_TIMEOUT_MS
      const result = await runCapture(ready.command, [...ready.args, '-m', ENGINE_MODULE, ...argv], {
        cwd: root,
        env: spawnEnv(pythonPathFor(cfg, env)),
        timeoutMs,
        signal: request.signal ?? null,
      })

      if (result.timedOut) {
        return failure('engine_timeout', `the engine did not finish within ${Math.round(timeoutMs / 1000)} s`, repairFor('engine_timeout'))
      }
      if (request.signal?.aborted) return failure('canceled', 'the call was aborted', repairFor('canceled'))
      if (result.error) {
        log?.warn?.(`engine spawn failed: ${firstLine(result.error, 200)}`)
        return failure('engine_unavailable', 'could not start the Python engine', repairFor('engine_unavailable'))
      }
      if (result.truncated) {
        log?.warn?.('engine output exceeded the capture limit')
        return failure('engine_failed', 'the engine produced more output than the plugin accepts', repairFor('failed'))
      }

      const parsed = parseEngineStdout(result.stdout)
      if (!parsed.ok) return failure(parsed.code, parsed.message, repairFor(parsed.code))

      const payload = parsed.payload
      if (payload.ok === false) return failureFromPayload(payload)
      if (result.exitCode !== 0 && payload.ok !== true) {
        return failure('engine_failed', `the engine exited with code ${result.exitCode}`, repairFor('engine_failed'))
      }
      return { ok: true, payload }
    } catch (error) {
      log?.warn?.(`engine bridge failure: ${messageOf(error)}`)
      return failure('failed', 'the engine bridge failed unexpectedly', repairFor('failed'))
    }
  }

  /**
   * Run one arbitrary engine CLI command with explicit argv.
   *
   * The panel/export routes are not model tools, so they use this raw entry
   * point instead of `buildEngineArgs`. Envelope, timeout and never-throw
   * behaviour are identical to `run()`.
   *
   * @param {{
   *   command: string,
   *   root: string,
   *   cacheDir?: string,
   *   args?: string[],
   *   timeoutMs?: number,
   *   signal?: AbortSignal | null,
   * }} request
   * @returns {Promise<{ok: true, payload: object} | {ok: false, code: string, message: string, repair: object}>}
   */
  async function runRaw(request = {}) {
    try {
      const command = typeof request.command === 'string' ? request.command.trim() : ''
      if (command.length === 0) return failure('invalid_args', 'missing engine command', repairFor('invalid_args'))
      const root = typeof request.root === 'string' ? request.root : ''
      if (root.length === 0) return failure('workspace_unavailable', 'no workspace root was resolved', repairFor('failed'))
      if (request.signal?.aborted) return failure('canceled', 'the call was aborted before the engine started', repairFor('canceled'))

      const ready = await probe()
      if (!ready.ready) return failure('engine_unavailable', ready.error, repairFor('engine_unavailable'))

      const cacheDir = typeof request.cacheDir === 'string' && request.cacheDir.length > 0 ? request.cacheDir : cacheDirFor(cfg, root)
      try {
        mkdirSync(cacheDir, { recursive: true })
      } catch {
        log?.warn?.(`could not create the index cache directory ${cacheDir}`)
        return failure('engine_failed', 'the plugin could not prepare its index cache directory', repairFor('failed'))
      }

      const extra = Array.isArray(request.args) ? request.args.map((item) => String(item)) : []
      const argv = [command, '--json', '--root', root, '--cache-dir', cacheDir, ...extra]
      const timeoutMs = Number.isInteger(request.timeoutMs)
        ? request.timeoutMs
        : Number.isInteger(cfg.timeoutMs)
          ? cfg.timeoutMs
          : DEFAULT_TIMEOUT_MS
      const result = await runCapture(ready.command, [...ready.args, '-m', ENGINE_MODULE, ...argv], {
        cwd: root,
        env: spawnEnv(pythonPathFor(cfg, env)),
        timeoutMs,
        signal: request.signal ?? null,
      })

      if (result.timedOut) {
        return failure('engine_timeout', `the engine did not finish within ${Math.round(timeoutMs / 1000)} s`, repairFor('engine_timeout'))
      }
      if (request.signal?.aborted) return failure('canceled', 'the call was aborted', repairFor('canceled'))
      if (result.error) {
        log?.warn?.(`engine spawn failed: ${firstLine(result.error, 200)}`)
        return failure('engine_unavailable', 'could not start the Python engine', repairFor('engine_unavailable'))
      }
      if (result.truncated) {
        log?.warn?.('engine output exceeded the capture limit')
        return failure('engine_failed', 'the engine produced more output than the plugin accepts', repairFor('failed'))
      }
      const parsed = parseEngineStdout(result.stdout)
      if (!parsed.ok) return failure(parsed.code, parsed.message, repairFor(parsed.code))
      const payload = parsed.payload
      if (payload.ok === false) return failureFromPayload(payload)
      if (result.exitCode !== 0 && payload.ok !== true) {
        return failure('engine_failed', `the engine exited with code ${result.exitCode}`, repairFor('engine_failed'))
      }
      return { ok: true, payload }
    } catch (error) {
      log?.warn?.(`engine bridge failure: ${messageOf(error)}`)
      return failure('failed', 'the engine bridge failed unexpectedly', repairFor('failed'))
    }
  }

  return { probe, run, runRaw, invalidate, candidates: () => (candidates === null ? candidateList({ cfg, env }) : candidates) }
}

/** Build one never-throw failure envelope. */
function failure(code, message, repair) {
  return { ok: false, code, message: boundMessage(message), repair: repair ?? repairFor(code) }
}

/** Map the engine's own failure envelope into the plugin envelope. */
function failureFromPayload(payload) {
  const error = isPlainObject(payload.error) ? payload.error : payload
  const rawCode = typeof error.code === 'string' ? error.code.trim() : ''
  const code = /^[a-z][a-z0-9_]{0,63}$/u.test(rawCode) ? rawCode : 'engine_failed'
  const message = typeof error.message === 'string' && error.message.trim().length > 0 ? error.message.trim() : 'the engine reported a failure'
  return failure(code, message, repairFor(code))
}

function boundMessage(value) {
  const text = typeof value === 'string' ? value.trim() : 'the engine reported a failure'
  if (text.length === 0) return 'the engine reported a failure'
  return text.length > 500 ? `${text.slice(0, 497)}...` : text
}

function summarizeAttempts(attempts) {
  return attempts
    .slice(0, 8)
    .map((attempt) => `${attempt.candidate}: ${attempt.error}`)
    .join('; ')
}

/** Parse the last non-empty stdout line as JSON (the probe contract). */
function parseLastJsonLine(text) {
  const lines = String(text ?? '')
    .split(/\r?\n/u)
    .filter((line) => line.trim().length > 0)
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try {
      const value = JSON.parse(lines[index])
      if (isPlainObject(value)) return value
    } catch {
      /* keep looking */
    }
  }
  return null
}

/**
 * Parse the engine's stdout into exactly one JSON object.
 *
 * The contract is one object + trailing newline; the tolerant fallbacks (last
 * line, first-to-last brace) only exist so a stray warning line does not turn
 * into a confusing failure. Anything else becomes `engine_invalid_json` — the
 * raw text is never returned in the envelope.
 *
 * @param {string} stdout captured stdout
 * @returns {{ok: true, payload: object} | {ok: false, code: string, message: string}}
 */
export function parseEngineStdout(stdout) {
  const text = String(stdout ?? '').trim()
  if (text.length === 0) return { ok: false, code: 'engine_invalid_json', message: 'the engine returned no output' }
  const direct = tryParseObject(text)
  if (direct !== null) return { ok: true, payload: direct }
  const lines = text.split(/\r?\n/u).filter((line) => line.trim().length > 0)
  const last = tryParseObject(lines[lines.length - 1] ?? '')
  if (last !== null) return { ok: true, payload: last }
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start >= 0 && end > start) {
    const sliced = tryParseObject(text.slice(start, end + 1))
    if (sliced !== null) return { ok: true, payload: sliced }
  }
  return { ok: false, code: 'engine_invalid_json', message: 'the engine returned invalid JSON' }
}

function tryParseObject(text) {
  if (typeof text !== 'string' || text.length === 0) return null
  try {
    const value = JSON.parse(text)
    return isPlainObject(value) ? value : null
  } catch {
    return null
  }
}

/** Child environment: UTF-8 Python stdio, no Electron-as-Node inheritance. */
function spawnEnv(pythonPath) {
  const childEnv = { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1', PYTHONUNBUFFERED: '1' }
  delete childEnv.ELECTRON_RUN_AS_NODE
  if (typeof pythonPath === 'string' && pythonPath.length > 0) childEnv.PYTHONPATH = pythonPath
  return childEnv
}

/**
 * Run a command to completion with a timeout and bounded UTF-8 capture.
 *
 * @param {string} command executable
 * @param {string[]} args arguments
 * @param {{cwd?: string, env?: Record<string, string | undefined>, timeoutMs?: number, signal?: AbortSignal | null}} [options]
 * @returns {Promise<{exitCode: number | null, timedOut: boolean, truncated: boolean, stdout: string, stderr: string, error: string | null}>}
 */
function runCapture(command, args, options = {}) {
  const { cwd = PLUGIN_DIR, env = process.env, timeoutMs = DEFAULT_TIMEOUT_MS, signal = null } = options
  return new Promise((resolvePromise) => {
    const capture = { stdout: '', stderr: '', truncated: false }
    let timedOut = false
    let settled = false
    let child = null
    const finish = (extra = {}) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolvePromise({
        exitCode: extra.exitCode ?? null,
        timedOut,
        truncated: capture.truncated,
        stdout: capture.stdout,
        stderr: capture.stderr,
        error: extra.error ?? null,
      })
    }
    const timer = setTimeout(() => {
      timedOut = true
      try {
        child?.kill('SIGKILL')
      } catch {
        /* the child may have exited between the timer and the kill */
      }
    }, timeoutMs)
    try {
      child = spawn(command, args, {
        cwd,
        env,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
        ...(signal === null ? {} : { signal }),
      })
    } catch (error) {
      finish({ error: messageOf(error) })
      return
    }
    child.stdout?.on('data', (chunk) => appendCapture(capture, 'stdout', chunk))
    child.stderr?.on('data', (chunk) => appendCapture(capture, 'stderr', chunk))
    child.on('error', (error) => finish({ error: messageOf(error) }))
    child.on('close', (code) => finish({ exitCode: code }))
  })
}

function appendCapture(capture, key, chunk) {
  if (capture[key].length >= MAX_CAPTURE_BYTES) {
    capture.truncated = true
    return
  }
  const text = String(chunk)
  const room = MAX_CAPTURE_BYTES - capture[key].length
  if (text.length > room) {
    capture[key] += text.slice(0, room)
    capture.truncated = true
    return
  }
  capture[key] += text
}
