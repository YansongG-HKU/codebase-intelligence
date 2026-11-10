/**
 * The plugin service: one object shared by the six tools.
 *
 * Responsibilities, in order of importance:
 *
 * 1. **Read-only boundary.** Every call resolves one workspace root from the
 *    Agent's session (`header.cwd` → `header.config.cwd` → `agent.cwd` →
 *    `process.cwd()`), validates path-like arguments as repository-relative
 *    POSIX paths, and hands the engine that root plus a cache directory that
 *    lives under the plugin data dir — never under the workspace.
 * 2. **Never throw.** Any validation, spawn or engine failure becomes the
 *    shared `{ok:false, code, message, repair}` envelope.
 * 3. **Determinism.** A bounded in-memory payload memo returns the exact same
 *    bytes for repeated identical calls. Entries record the engine's
 *    `index.fingerprint` and are guarded by a cheap workspace stat stamp; a
 *    changed workspace forces a fresh engine call. Cache state is never
 *    present in a tool value.
 *
 * @module dsh-codebase-intelligence/service
 */

import { readdirSync, statSync } from 'node:fs'
import { isAbsolute, join, relative, resolve } from 'node:path'

import { createBridge, repairFor } from './bridge.js'
import { resolveMaxTokens, TOOL_KEYS } from './config.js'
import { cacheDirFor, isWithin } from './paths.js'
import { canonicalJson, deepClone, isPlainObject, messageOf, sha256Hex, utf8Bytes } from './util.js'

/** Maximum memoized payload entries per plugin instance. */
const MEMO_MAX_ENTRIES = 64
/** Maximum total memoized payload bytes per plugin instance. */
const MEMO_MAX_BYTES = 6 * 1024 * 1024
/** Maximum filesystem entries inspected by one workspace stamp. */
const STAMP_MAX_ENTRIES = 4_096
/** Maximum directory depth inspected by one workspace stamp. */
const STAMP_MAX_DEPTH = 6
/** Bounded free-text argument length (query/task). */
const MAX_TEXT_CHARS = 4_000
/** Bounded list sizes for impact arguments. */
const MAX_FILES = 50
const MAX_SYMBOLS = 100
/** Directories never descended into by the stat stamp (they are also excluded from the index by default). */
const STAMP_EXCLUDED_DIRS = new Set([
  '.git',
  '.hg',
  '.svn',
  '.venv',
  'venv',
  'node_modules',
  '__pycache__',
  'build',
  'dist',
  'target',
  'vendor',
  '.mypy_cache',
  '.pytest_cache',
  '.ruff_cache',
  '.idea',
  '.vscode',
  '.codebase-intelligence',
])

/** Local repair hints for failures raised by the plugin itself. */
const SERVICE_REPAIR = Object.freeze({
  workspace_unavailable: {
    action: 'check-workspace',
    label: 'Start the session in a readable repository directory',
    detail: 'The plugin resolves the workspace from the session cwd; a session whose cwd does not exist has no repository to inspect.',
  },
  workspace_boundary: {
    action: 'fix-arguments',
    label: 'Use a repository-relative path inside the session workspace',
    detail: 'Absolute paths, drive letters and parent-directory segments are rejected before the engine is called.',
  },
})

/**
 * Create the per-plugin service.
 *
 * @param {{
 *   cfg: object,
 *   log?: {info?: Function, warn?: Function} | null,
 *   bridge?: object | null,
 * }} options resolved config and (for tests) an injected bridge
 */
export function createService({ cfg, log = null, bridge = null } = {}) {
  const engine = bridge ?? createBridge({ cfg, log })
  /** Memo entries keyed by root + tool + canonical args + budget. */
  const memo = new Map()
  let memoBytes = 0

  /** Resolve the workspace root from a live Agent, falling back to `process.cwd()`. */
  function resolveWorkspaceRoot(agent, { fallback = process.cwd() } = {}) {
    const header = agent?.session?.header
    const raw = header?.cwd ?? header?.config?.cwd ?? agent?.cwd ?? fallback
    if (typeof raw !== 'string' || raw.trim().length === 0) {
      return { ok: false, message: 'no workspace directory could be resolved for this session' }
    }
    let root
    try {
      root = resolve(raw.trim())
      if (!statSync(root).isDirectory()) {
        return { ok: false, message: 'the session workspace is not a directory' }
      }
    } catch {
      return { ok: false, message: 'the session workspace directory does not exist or is not readable' }
    }
    return { ok: true, root }
  }

  /** sessionId → workspace root for panel/web requests (filled by agent decoration). */
  const sessionRoots = new Map()
  let lastRoot = null

  /**
   * Remember one live Agent's session workspace so the panel (which has no
   * Agent object of its own) can resolve a repository root by session id.
   *
   * @param {object} agent live Agent (session.header.cwd)
   * @returns {boolean} whether a root was recorded
   */
  function registerSession(agent) {
    try {
      const header = agent?.session?.header ?? {}
      const raw = header?.cwd ?? header?.config?.cwd ?? agent?.cwd
      if (typeof raw !== 'string' || raw.trim().length === 0) return false
      const root = resolve(raw.trim())
      lastRoot = root
      for (const id of [agent?.id, agent?.session?.id, header?.id, header?.sessionId]) {
        if (typeof id === 'string' && id.length > 0) sessionRoots.set(id, root)
      }
      return true
    } catch {
      return false
    }
  }

  /** Resolve the panel's repository root: exact session id first, then the latest one. */
  function resolveSessionRoot(sessionId) {
    if (typeof sessionId === 'string' && sessionId.length > 0 && sessionRoots.has(sessionId)) {
      return sessionRoots.get(sessionId)
    }
    return lastRoot
  }

  /** Minimal agent-shaped object so panel calls share the six-tool pipeline. */
  function syntheticAgent(root) {
    return { session: { header: { cwd: root } } }
  }

  /**
   * Execute one read-only tool on behalf of the panel.
   *
   * @param {string} toolKey short tool key
   * @param {unknown} rawArgs tool-shaped arguments
   * @param {{sessionId?: string | null, signal?: AbortSignal | null}} [options]
   */
  async function panelCall(toolKey, rawArgs, options = {}) {
    const root = resolveSessionRoot(options.sessionId)
    if (root === null) {
      return failure('workspace_unavailable', 'no live session workspace yet; open a session in a repository first', repair('workspace_unavailable'))
    }
    return call(toolKey, rawArgs, { agent: syntheticAgent(root), signal: options.signal ?? null })
  }

  /**
   * Run the deterministic export command (`--check` for a plan, otherwise write).
   *
   * @param {{sessionId?: string | null, check?: boolean, signal?: AbortSignal | null}} [options]
   */
  async function runExport(options = {}) {
    const root = resolveSessionRoot(options.sessionId)
    if (root === null) {
      return failure('workspace_unavailable', 'no live session workspace yet; open a session in a repository first', repair('workspace_unavailable'))
    }
    if (typeof engine.runRaw !== 'function') {
      return failure('engine_unavailable', 'the export command is not available in this plugin build', repairFor('engine_unavailable'))
    }
    const args = ['--out', cfg.exportDir]
    if (options.check === true) args.push('--check')
    return engine.runRaw({
      command: 'export',
      root,
      cacheDir: cacheDirFor(cfg, root),
      args,
      signal: options.signal ?? null,
    })
  }

  /** Export preview (writes nothing). */
  function exportPreview(options = {}) {
    return runExport({ ...options, check: true })
  }

  /** Export write (explicit, confirmed by the caller). */
  function exportWrite(options = {}) {
    return runExport({ ...options, check: false })
  }

  /**
   * Execute one tool call. Resolves to the engine payload on success or the
   * shared error envelope on any failure; never rejects.
   *
   * @param {string} toolKey short tool key
   * @param {unknown} rawArgs model-provided arguments
   * @param {{agent?: object, signal?: AbortSignal}} [options]
   * @returns {Promise<object>} payload or `{ok:false, code, message, repair}`
   */
  async function call(toolKey, rawArgs, options = {}) {
    try {
      if (!TOOL_KEYS.includes(toolKey)) {
        return failure('invalid_args', `unknown tool key ${JSON.stringify(toolKey)}`, repairFor('invalid_args'))
      }
      const workspace = resolveWorkspaceRoot(options.agent)
      if (!workspace.ok) return failure('workspace_unavailable', workspace.message, repair('workspace_unavailable'))

      const collected = collectArgs(toolKey, rawArgs, workspace.root)
      if (!collected.ok) {
        return failure(collected.code ?? 'invalid_args', collected.message, repair(collected.code ?? 'invalid_args'))
      }
      const maxTokens = resolveMaxTokens(cfg, toolKey, isPlainObject(rawArgs) ? rawArgs.maxTokens : undefined)
      const cacheDir = cacheDirFor(cfg, workspace.root)
      // `refresh` bypasses and replaces the memo entry, so it is not part of the key.
      const memoArgs = { ...collected.args }
      delete memoArgs.refresh
      const key = `${workspace.root}\u0000${toolKey}\u0000${canonicalJson(memoArgs)}\u0000${maxTokens}`
      const stamp = workspaceStamp(workspace.root)

      if (collected.args.refresh !== true) {
        const hit = memo.get(key)
        if (hit && hit.stamp === stamp) return deepClone(hit.payload)
      }

      const result = await engine.run(toolKey, {
        root: workspace.root,
        cacheDir,
        maxTokens,
        args: collected.args,
        signal: options.signal ?? null,
      })
      if (!result || result.ok !== true) {
        const envelope = isPlainObject(result) && result.ok === false ? result : null
        if (envelope !== null) return normalizeFailure(envelope)
        return failure('failed', 'the engine returned no result', repairFor('failed'))
      }
      if (!isPlainObject(result.payload)) {
        return failure('engine_invalid_json', 'the engine returned an invalid payload', repairFor('engine_invalid_json'))
      }
      const payload = result.payload
      memoStore(key, {
        stamp,
        fingerprint: typeof payload.index?.fingerprint === 'string' ? payload.index.fingerprint : null,
        payload,
      })
      return deepClone(payload)
    } catch (error) {
      log?.warn?.(`tool ${toolKey} failed: ${messageOf(error)}`)
      return failure('failed', 'the tool failed unexpectedly', repairFor('failed'))
    }
  }

  function memoStore(key, entry) {
    const bytes = utf8Bytes(JSON.stringify(entry.payload))
    if (bytes > MEMO_MAX_BYTES) return
    const previous = memo.get(key)
    if (previous !== undefined) {
      memoBytes -= utf8Bytes(JSON.stringify(previous.payload))
      memo.delete(key)
    }
    memo.set(key, { ...entry, bytes })
    memoBytes += bytes
    while (memo.size > MEMO_MAX_ENTRIES || memoBytes > MEMO_MAX_BYTES) {
      const oldestKey = memo.keys().next().value
      if (oldestKey === undefined) break
      const oldest = memo.get(oldestKey)
      memo.delete(oldestKey)
      memoBytes -= oldest?.bytes ?? 0
    }
  }

  return {
    cfg,
    bridge: engine,
    resolveWorkspaceRoot,
    resolveSessionRoot,
    registerSession,
    panelCall,
    exportPreview,
    exportWrite,
    call,
    /** Forget memoized payloads and the interpreter probe (no tool value changes). */
    invalidate() {
      memo.clear()
      memoBytes = 0
      engine.invalidate?.()
    },
  }
}

/** Build one never-throw failure envelope (path-free message). */
function failure(code, message, repairEnvelope) {
  return { ok: false, code, message: boundMessage(message), repair: repairEnvelope ?? repairFor(code) }
}

function repair(code) {
  return SERVICE_REPAIR[code] ?? repairFor(code)
}

/** Strip unknown fields from an engine-originated failure envelope. */
function normalizeFailure(envelope) {
  const code = typeof envelope.code === 'string' && /^[a-z][a-z0-9_]{0,63}$/u.test(envelope.code) ? envelope.code : 'engine_failed'
  const message = typeof envelope.message === 'string' && envelope.message.trim().length > 0 ? envelope.message : 'the engine reported a failure'
  const repairEnvelope = isPlainObject(envelope.repair) ? envelope.repair : repairFor(code)
  return { ok: false, code, message: boundMessage(message), repair: repairEnvelope }
}

function boundMessage(value) {
  const text = typeof value === 'string' ? value.trim() : ''
  const fallback = 'the tool failed'
  if (text.length === 0) return fallback
  return text.length > 500 ? `${text.slice(0, 497)}...` : text
}

/**
 * Validate and normalize the arguments of one tool into the engine-facing
 * shape. Free text is bounded; path-like values must stay inside the workspace.
 *
 * @returns {{ok: true, args: object} | {ok: false, code?: string, message: string}}
 */
function collectArgs(toolKey, rawArgs, root) {
  const raw = isPlainObject(rawArgs) ? rawArgs : {}
  const args = {}
  if (raw.refresh === true) args.refresh = true

  switch (toolKey) {
    case 'overview':
      return { ok: true, args }
    case 'map': {
      if (raw.focus !== undefined && raw.focus !== null && raw.focus !== '') {
        const focus = normalizeRepoPath(raw.focus)
        if (!focus.ok) return focus
        args.focus = focus.value
      }
      return { ok: true, args }
    }
    case 'search': {
      const query = requiredText(raw.query, 'query')
      if (!query.ok) return query
      args.query = query.value
      return { ok: true, args }
    }
    case 'dependencies': {
      const target = normalizeTarget(raw.target)
      if (!target.ok) return target
      args.target = target.value
      const direction = raw.direction === undefined || raw.direction === null ? 'both' : raw.direction
      if (direction !== 'both' && direction !== 'imports' && direction !== 'dependents') {
        return { ok: false, code: 'invalid_args', message: 'direction must be one of both, imports or dependents' }
      }
      args.direction = direction
      const depth = raw.depth === undefined || raw.depth === null ? 1 : raw.depth
      if (!Number.isInteger(depth) || depth < 1 || depth > 5) {
        return { ok: false, code: 'invalid_args', message: 'depth must be an integer between 1 and 5' }
      }
      args.depth = depth
      return { ok: true, args }
    }
    case 'context': {
      const task = requiredText(raw.task, 'task')
      if (!task.ok) return task
      args.task = task.value
      if (raw.pathPrefix !== undefined && raw.pathPrefix !== null && raw.pathPrefix !== '') {
        const prefix = normalizeRepoPath(raw.pathPrefix)
        if (!prefix.ok) return prefix
        args.pathPrefix = prefix.value
      }
      return { ok: true, args }
    }
    case 'impact': {
      const files = normalizePathList(raw.files, 'files', MAX_FILES, root)
      if (!files.ok) return files
      const symbols = normalizeSymbolList(raw.symbols, 'symbols', MAX_SYMBOLS)
      if (!symbols.ok) return symbols
      if (files.items.length === 0 && symbols.items.length === 0) {
        return { ok: false, code: 'invalid_args', message: 'provide at least one file (files) or symbol (symbols)' }
      }
      args.files = files.items
      args.symbols = symbols.items
      return { ok: true, args }
    }
    default:
      return { ok: false, code: 'invalid_args', message: `unknown tool key ${JSON.stringify(toolKey)}` }
  }
}

/** Bounded free-text argument (query/task). */
function requiredText(value, field) {
  if (typeof value !== 'string' || value.trim().length === 0) {
    return { ok: false, code: 'invalid_args', message: `${field} is required and must be a non-empty string` }
  }
  const trimmed = value.trim()
  if (trimmed.length > MAX_TEXT_CHARS) {
    return { ok: false, code: 'invalid_args', message: `${field} must be at most ${MAX_TEXT_CHARS} characters` }
  }
  return { ok: true, value: trimmed }
}

/**
 * Normalize one repository-relative POSIX path.
 *
 * Rejects absolute paths, drive letters, `~` and parent-directory segments;
 * this is defense in depth — the engine independently resolves every path with
 * `strict` containment checks.
 *
 * @param {unknown} value raw value
 * @returns {{ok: true, value: string} | {ok: false, code: string, message: string}}
 */
export function normalizeRepoPath(value) {
  if (typeof value !== 'string') {
    return { ok: false, code: 'invalid_args', message: 'path arguments must be strings' }
  }
  const trimmed = value.trim()
  if (trimmed.length === 0) return { ok: false, code: 'invalid_args', message: 'path arguments must not be empty' }
  if (trimmed.length > 1_024) return { ok: false, code: 'invalid_args', message: 'path arguments must be at most 1024 characters' }
  const posix = trimmed.replace(/\\/gu, '/')
  if (/^[A-Za-z]:/u.test(posix) || posix.startsWith('/') || posix.startsWith('~')) {
    return {
      ok: false,
      code: 'workspace_boundary',
      message: 'path arguments must be repository-relative, not absolute or home-relative',
    }
  }
  const segments = posix.split('/').filter((segment) => segment.length > 0 && segment !== '.')
  if (segments.length === 0) return { ok: false, code: 'invalid_args', message: 'path arguments must name a file or directory' }
  if (segments.some((segment) => segment === '..')) {
    return { ok: false, code: 'workspace_boundary', message: 'path arguments must not contain a parent-directory segment' }
  }
  return { ok: true, value: segments.join('/') }
}

/** Normalize a `--target` value: symbol id, repository path, or bare symbol name. */
function normalizeTarget(value) {
  if (typeof value !== 'string' || value.trim().length === 0) {
    return { ok: false, code: 'invalid_args', message: 'target is required and must be a non-empty string' }
  }
  const trimmed = value.trim()
  if (trimmed.length > 1_024) return { ok: false, code: 'invalid_args', message: 'target must be at most 1024 characters' }
  const posix = trimmed.replace(/\\/gu, '/')
  if (/^[A-Za-z]:/u.test(posix) || posix.startsWith('/') || posix.startsWith('~')) {
    return { ok: false, code: 'workspace_boundary', message: 'target must refer to a file or symbol inside the workspace' }
  }
  if (posix.split('/').some((segment) => segment === '..')) {
    return { ok: false, code: 'workspace_boundary', message: 'target must not contain a parent-directory segment' }
  }
  if (trimmed.startsWith('sym:') || trimmed.startsWith('file:')) return { ok: true, value: trimmed }
  if (trimmed.includes('/') || trimmed.includes('\\')) return normalizeRepoPath(trimmed)
  return { ok: true, value: trimmed }
}

/** Validate a list of repository paths (impact `files`). */
function normalizePathList(value, field, limit, root) {
  if (value === undefined || value === null) return { ok: true, items: [] }
  if (!Array.isArray(value)) return { ok: false, code: 'invalid_args', message: `${field} must be an array of repository-relative paths` }
  if (value.length > limit) return { ok: false, code: 'invalid_args', message: `${field} accepts at most ${limit} entries` }
  const items = []
  for (const entry of value) {
    const normalized = normalizeRepoPath(entry)
    if (!normalized.ok) return normalized
    const absolute = resolve(root, ...normalized.value.split('/'))
    if (!isWithin(root, absolute)) {
      return { ok: false, code: 'workspace_boundary', message: `${field} entries must stay inside the session workspace` }
    }
    items.push(normalized.value)
  }
  return { ok: true, items: dedupe(items) }
}

/** Validate a list of symbol ids/names (impact `symbols`). */
function normalizeSymbolList(value, field, limit) {
  if (value === undefined || value === null) return { ok: true, items: [] }
  if (!Array.isArray(value)) return { ok: false, code: 'invalid_args', message: `${field} must be an array of symbol ids or names` }
  if (value.length > limit) return { ok: false, code: 'invalid_args', message: `${field} accepts at most ${limit} entries` }
  const items = []
  for (const entry of value) {
    if (typeof entry !== 'string' || entry.trim().length === 0) {
      return { ok: false, code: 'invalid_args', message: `${field} entries must be non-empty strings` }
    }
    const trimmed = entry.trim()
    if (trimmed.length > 1_024) return { ok: false, code: 'invalid_args', message: `${field} entries must be at most 1024 characters` }
    const posix = trimmed.replace(/\\/gu, '/')
    if (/^[A-Za-z]:/u.test(posix) || posix.startsWith('/') || posix.split('/').some((segment) => segment === '..')) {
      return { ok: false, code: 'workspace_boundary', message: `${field} entries must not contain absolute paths or parent-directory segments` }
    }
    items.push(trimmed)
  }
  return { ok: true, items: dedupe(items) }
}

function dedupe(items) {
  const seen = new Set()
  const out = []
  for (const item of items) {
    if (seen.has(item)) continue
    seen.add(item)
    out.push(item)
  }
  return out
}

/**
 * Cheap bounded stat stamp of a workspace: names, sizes and mtimes of up to
 * 4096 entries at depth ≤ 6, excluding the directories the scanner excludes by
 * default. Deterministic for identical filesystem state; used only to decide
 * whether a memoized payload may still be returned.
 *
 * @param {string} root absolute workspace root
 * @returns {string} 16-hex stamp
 */
export function workspaceStamp(root) {
  const entries = []
  const queue = [{ dir: root, depth: 0 }]
  try {
    while (queue.length > 0 && entries.length < STAMP_MAX_ENTRIES) {
      const current = queue.shift()
      let dirents
      try {
        dirents = readdirSync(current.dir, { withFileTypes: true })
      } catch {
        entries.push(`e:${current.depth}`)
        continue
      }
      dirents.sort((left, right) => (left.name < right.name ? -1 : left.name > right.name ? 1 : 0))
      for (const dirent of dirents) {
        if (entries.length >= STAMP_MAX_ENTRIES) break
        const absolute = join(current.dir, dirent.name)
        const rel = relative(root, absolute).split('\\').join('/')
        if (dirent.isDirectory()) {
          entries.push(`d:${rel}`)
          if (!STAMP_EXCLUDED_DIRS.has(dirent.name) && current.depth < STAMP_MAX_DEPTH) {
            queue.push({ dir: absolute, depth: current.depth + 1 })
          }
        } else if (dirent.isFile()) {
          try {
            const stats = statSync(absolute)
            entries.push(`f:${rel}:${stats.size}:${Math.trunc(stats.mtimeMs)}`)
          } catch {
            entries.push(`f:${rel}:?`)
          }
        } else {
          entries.push(`o:${rel}`)
        }
      }
    }
  } catch {
    return ''
  }
  if (entries.length >= STAMP_MAX_ENTRIES) entries.push('cap')
  return sha256Hex(entries.join('\n')).slice(0, 16)
}
