/**
 * dsh-codebase-intelligence — Host half of the panel: loopback, same-origin JSON
 * routes for the right-sidebar / full-page client and the deterministic export
 * writer.
 *
 * Follows the proven `dsh-security-selftest` shape:
 *   - registered only through `ctx.inject(['webServer'])`, so a headless profile
 *     never fails activation (`registerPanel` returns null there);
 *   - every request needs a loopback Host, the
 *     `x-dsh-codebase-intelligence: 1` header and a matching Origin when present;
 *   - every response is JSON with `no-store`; handlers never throw into the web
 *     server; JSON bodies are capped at 1 MiB;
 *   - the Host only ever reads git state and writes the generation directory via
 *     the engine's `cbi export`; it never stages, commits or pushes.
 *
 * The route table is normative in PANEL_CONTRACT.md §3.
 *
 * @module dsh-codebase-intelligence/panel
 */

import { execFile } from 'node:child_process'

import { DEFAULT_MAX_TOKENS, MAX_TOKENS_LIMIT, MIN_MAX_TOKENS } from './config.js'
import { isPlainObject, messageOf } from './util.js'

/** Same-origin marker the client sends. */
export const REQUEST_HEADER = 'x-dsh-codebase-intelligence'
/** URL prefix of every panel route. */
export const ROUTE_PREFIX = '/dsh-codebase-intelligence'
/** Largest accepted JSON request body. */
export const MAX_BODY_BYTES = 1_048_576

const GET = 'GET'
const POST = 'POST'
const MAX_QUERY_CHARS = 4_000
const GIT_TIMEOUT_MS = 5_000

/**
 * Route table: full-path anchored patterns, most specific first.
 */
export const ROUTES = Object.freeze([
  { route: 'state', methods: Object.freeze([GET]), pattern: /^\/dsh-codebase-intelligence\/api\/state$/u },
  { route: 'overview', methods: Object.freeze([GET]), pattern: /^\/dsh-codebase-intelligence\/api\/overview$/u },
  { route: 'map', methods: Object.freeze([GET]), pattern: /^\/dsh-codebase-intelligence\/api\/map$/u },
  { route: 'graph', methods: Object.freeze([GET, POST]), pattern: /^\/dsh-codebase-intelligence\/api\/graph$/u },
  { route: 'search', methods: Object.freeze([GET]), pattern: /^\/dsh-codebase-intelligence\/api\/search$/u },
  { route: 'dependencies', methods: Object.freeze([GET]), pattern: /^\/dsh-codebase-intelligence\/api\/dependencies$/u },
  { route: 'context', methods: Object.freeze([GET]), pattern: /^\/dsh-codebase-intelligence\/api\/context$/u },
  { route: 'impact', methods: Object.freeze([GET]), pattern: /^\/dsh-codebase-intelligence\/api\/impact$/u },
  { route: 'refresh', methods: Object.freeze([POST]), pattern: /^\/dsh-codebase-intelligence\/api\/refresh$/u },
  { route: 'export', methods: Object.freeze([GET, POST]), pattern: /^\/dsh-codebase-intelligence\/api\/export$/u },
  { route: 'git', methods: Object.freeze([GET]), pattern: /^\/dsh-codebase-intelligence\/api\/git$/u },
])

/** Map a shared failure code to an HTTP status. */
export function statusForCode(code) {
  switch (code) {
    case 'invalid_arguments':
    case 'invalid_input':
      return 400
    case 'forbidden':
      return 403
    case 'not_found':
      return 404
    case 'method_not_allowed':
      return 405
    case 'stale_graph':
      return 409
    case 'too_large':
      return 413
    case 'workspace_unavailable':
    case 'engine_unavailable':
      return 503
    case 'engine_timeout':
      return 504
    default:
      return 500
  }
}

/** Derive the server origin for the same-origin check. */
export function serverOrigin(webServer) {
  try {
    const origin = webServer?.getOrigin?.()
    if (typeof origin === 'string' && origin.length > 0) return origin
  } catch {
    /* not bound yet */
  }
  const port = Number(webServer?.port)
  const protocol = webServer?.protocol === 'https:' ? 'https:' : 'http:'
  if (Number.isFinite(port) && port > 0) return `${protocol}//127.0.0.1:${port}`
  return ''
}

/** Compare origins treating 127.0.0.1/localhost/[::1] as one loopback peer. */
function sameLoopbackOrigin(a, b) {
  let first
  let second
  try {
    first = new URL(a)
    second = new URL(b)
  } catch {
    return false
  }
  const loopback = new Set(['127.0.0.1', 'localhost', '[::1]', '::1'])
  return (
    first.protocol === second.protocol &&
    first.port === second.port &&
    loopback.has(first.hostname.toLowerCase()) &&
    loopback.has(second.hostname.toLowerCase())
  )
}

/**
 * Same-origin gate shared with the panel tests.
 *
 * @param {object} webServer the `webServer` service (or a stub with port/protocol)
 * @param {object} req IncomingMessage-like request
 * @returns {{ok: true} | {ok: false, status: 403, reason: string}}
 */
export function checkRequestGate(webServer, req) {
  const headers = isPlainObject(req?.headers) ? req.headers : {}
  const marker = headers[REQUEST_HEADER]
  const hasMarker = marker === '1' || (Array.isArray(marker) && marker.includes('1'))
  if (!hasMarker) return { ok: false, status: 403, reason: `missing ${REQUEST_HEADER}: 1 header` }
  const host = typeof headers.host === 'string' ? headers.host : ''
  if (host.length === 0) return { ok: false, status: 403, reason: 'missing Host header' }
  const hostname = host.replace(/:\d+$/u, '').replace(/^\[|\]$/gu, '').toLowerCase()
  if (!['127.0.0.1', 'localhost', '::1'].includes(hostname)) return { ok: false, status: 403, reason: 'non-loopback Host header' }
  const origin = headers.origin
  if (origin !== undefined) {
    if (typeof origin !== 'string' || origin.length === 0) return { ok: false, status: 403, reason: 'invalid Origin header' }
    const expected = serverOrigin(webServer)
    if (expected.length === 0) {
      let parsed
      try {
        parsed = new URL(origin)
      } catch {
        return { ok: false, status: 403, reason: 'invalid Origin header' }
      }
      if (!['127.0.0.1', 'localhost', '[::1]', '::1'].includes(parsed.hostname.toLowerCase())) {
        return { ok: false, status: 403, reason: 'unexpected Origin' }
      }
      return { ok: true }
    }
    if (origin !== expected && !sameLoopbackOrigin(origin, expected)) {
      return { ok: false, status: 403, reason: 'Origin does not match this server' }
    }
  }
  return { ok: true }
}

/** Find a route descriptor for one pathname. */
export function matchRoute(pathname) {
  for (const descriptor of ROUTES) {
    if (descriptor.pattern.test(pathname)) return descriptor
  }
  return null
}

/**
 * Register the panel routes through the optional `webServer` service.
 *
 * @param {{ctx: object, service: object, log?: object, onExported?: Function}} options
 * @returns {unknown} Cordis effect disposer, or null when there is no web server
 */
export function registerPanel({ ctx, service, log = null, onExported = null } = {}) {
  if (!ctx || typeof ctx.inject !== 'function') return null
  try {
    return ctx.inject(['webServer'], (webCtx) => {
      const webServer = webCtx?.webServer
      if (!webServer || typeof webServer.register !== 'function') return null
      const register = () => {
        return webServer.register({
          kind: 'prefix',
          path: ROUTE_PREFIX,
          handler: (req, res) => {
            void handleRequest(webCtx, service, req, res, { onExported })
          },
        })
      }
      if (typeof webCtx.effect === 'function') return webCtx.effect(register, 'dsh-codebase-intelligence: panel routes')
      return register()
    })
  } catch (error) {
    try {
      log?.warn?.(`could not register the panel routes: ${messageOf(error)}`)
    } catch {
      /* logging must never break activation */
    }
    return null
  }
}

/** Minimal JSON responder. */
export function sendJson(res, status, value) {
  try {
    if (!res || res.headersSent || res.writableEnded) return
    const body = JSON.stringify(value === undefined ? {} : value)
    res.writeHead(status, {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
      'content-length': String(Buffer.byteLength(body, 'utf8')),
    })
    res.end(body)
  } catch {
    /* a dead response must never escape into the web server */
  }
}

/** Read and parse a bounded JSON request body; empty bodies become `{}`. */
export async function readJsonBody(req, maxBytes = MAX_BODY_BYTES) {
  const chunks = []
  let total = 0
  if (req && typeof req[Symbol.asyncIterator] === 'function') {
    for await (const chunk of req) {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
      total += buffer.length
      if (total > maxBytes) {
        const error = new Error(`request body exceeds ${maxBytes} bytes`)
        error.code = 'too_large'
        throw error
      }
      chunks.push(buffer)
    }
  }
  if (total === 0) return {}
  const text = Buffer.concat(chunks).toString('utf8').trim()
  if (text.length === 0) return {}
  try {
    return JSON.parse(text)
  } catch {
    const error = new Error('request body must be valid JSON')
    error.code = 'invalid_input'
    throw error
  }
}

/** Run one git command (read-only) without throwing. */
function runGit(root, args, timeoutMs = GIT_TIMEOUT_MS) {
  return new Promise((resolvePromise) => {
    try {
      execFile(
        'git',
        ['--no-optional-locks', '--literal-pathspecs', '-c', 'core.fsmonitor=false', ...args],
        { cwd: root, timeout: timeoutMs, windowsHide: true, maxBuffer: 64 * 1024, encoding: 'utf8' },
        (error, stdout, stderr) => {
          resolvePromise({ ok: !error, stdout: typeof stdout === 'string' ? stdout : '', stderr: typeof stderr === 'string' ? stderr : '' })
        },
      )
    } catch {
      resolvePromise({ ok: false, stdout: '', stderr: 'git is not available' })
    }
  })
}

/**
 * Read-only git facts for the generation directory plus the suggested commit
 * command. The host never stages, commits or pushes.
 *
 * @param {string} root workspace root
 * @param {string} outDir repository-relative generation directory
 */
export async function gitFacts(root, outDir) {
  const safeDir = typeof outDir === 'string' && outDir.length > 0 ? outDir : 'docs/codebase-intelligence'
  const [symbolic, status] = await Promise.all([
    runGit(root, ['symbolic-ref', '--quiet', '--short', 'HEAD']),
    runGit(root, ['status', '--porcelain', '--', safeDir]),
  ])
  const branch = symbolic.ok ? symbolic : await runGit(root, ['rev-parse', '--short', 'HEAD'])
  const canSuggestCommand = status.ok && /^[A-Za-z0-9_.][A-Za-z0-9_./-]*$/u.test(safeDir)
  const lines = status.ok
    ? status.stdout
        .split(/\r?\n/u)
        .map((line) => line.trim())
        .filter((line) => line.length > 0)
        .slice(0, 50)
    : []
  return {
    available: status.ok,
    branch: branch.ok ? branch.stdout.trim() || null : null,
    dirty: lines.length > 0,
    exportChanges: lines,
    command: canSuggestCommand
      ? `git add -- ${safeDir} && git commit --only -m "docs: refresh codebase intelligence snapshot" -- ${safeDir}`
      : null,
  }
}

function queryOf(url) {
  const params = {}
  for (const [key, value] of url.searchParams.entries()) {
    params[key] = value.length > MAX_QUERY_CHARS ? value.slice(0, MAX_QUERY_CHARS) : value
  }
  return params
}

function readBudget(raw, toolKey) {
  const fallback = DEFAULT_MAX_TOKENS[toolKey] ?? 1200
  if (raw === undefined || raw === null || raw === '') return fallback
  const value = Number(raw)
  if (!Number.isFinite(value)) return fallback
  return Math.min(MAX_TOKENS_LIMIT, Math.max(MIN_MAX_TOKENS, Math.trunc(value)))
}

function splitList(raw) {
  if (typeof raw !== 'string' || raw.length === 0) return []
  return raw
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
    .slice(0, 100)
}

/** Route one request; never throws and always answers JSON. */
export async function handleRequest(webCtx, service, req, res, options = {}) {
  const webServer = webCtx?.webServer ?? null
  try {
    const gate = checkRequestGate(webServer, req)
    if (gate.ok !== true) {
      sendJson(res, 403, { ok: false, code: 'forbidden', message: `same-origin request required: ${gate.reason}` })
      return
    }
    let url
    try {
      url = new URL(String(req.url ?? '/'), 'http://localhost')
    } catch {
      sendJson(res, 400, { ok: false, code: 'invalid_input', message: 'invalid request URL' })
      return
    }
    const descriptor = matchRoute(url.pathname)
    if (!descriptor) {
      sendJson(res, 404, { ok: false, code: 'not_found', message: 'unknown dsh-codebase-intelligence route' })
      return
    }
    const method = String(req.method ?? GET).toUpperCase()
    if (!descriptor.methods.includes(method)) {
      sendJson(res, 405, { ok: false, code: 'method_not_allowed', message: `method ${method} is not allowed` })
      return
    }
    let body = {}
    if (method === POST) body = await readJsonBody(req)
    const result = await dispatch({ service, url, descriptor, method, body, options })
    if (!isPlainObject(result) || result.ok !== true) {
      const code = isPlainObject(result) && typeof result.code === 'string' ? result.code : 'failed'
      const payload = isPlainObject(result)
        ? result
        : { ok: false, code: 'failed', message: 'the panel handler returned an empty result' }
      sendJson(res, statusForCode(code), payload)
      return
    }
    sendJson(res, 200, result)
  } catch (error) {
    const code = error && error.code === 'too_large' ? 'too_large' : error && error.code === 'invalid_input' ? 'invalid_input' : 'failed'
    try {
      sendJson(res, statusForCode(code), { ok: false, code, message: messageOf(error) })
    } catch {
      /* response may be gone */
    }
  }
}

/** Execute one matched route. */
export async function dispatch({ service, url, descriptor, method, body, options = {} }) {
  const query = queryOf(url)
  const bodySession = isPlainObject(body) && typeof body.session === 'string' && body.session.length > 0 ? body.session : null
  const sessionId =
    typeof query.session === 'string' && query.session.length > 0 ? query.session : bodySession
  switch (descriptor.route) {
    case 'state':
      return panelState(service, sessionId)
    case 'overview':
      return panelTool(service, 'overview', { maxTokens: readBudget(query.maxTokens, 'overview') }, sessionId)
    case 'map':
      return panelTool(
        service,
        'map',
        { maxTokens: readBudget(query.maxTokens, 'map'), focus: query.focus || undefined },
        sessionId,
      )
    case 'graph': {
      const result = method === POST
        ? await service.panelGraph({}, { sessionId, refresh: true })
        : await service.panelGraph(query, { sessionId })
      return result.ok === true ? { ok: true, data: result.payload } : result
    }
    case 'search':
      return panelTool(service, 'search', { query: query.query ?? '', maxTokens: readBudget(query.maxTokens, 'search') }, sessionId)
    case 'dependencies':
      return panelTool(
        service,
        'dependencies',
        {
          target: query.target ?? '',
          direction: query.direction ?? 'both',
          depth: Number(query.depth ?? 1),
          maxTokens: readBudget(query.maxTokens, 'dependencies'),
        },
        sessionId,
      )
    case 'context':
      return panelTool(
        service,
        'context',
        { task: query.task ?? '', maxTokens: readBudget(query.maxTokens, 'context'), pathPrefix: query.pathPrefix || undefined },
        sessionId,
      )
    case 'impact':
      return panelTool(
        service,
        'impact',
        { files: splitList(query.files), symbols: splitList(query.symbols), maxTokens: readBudget(query.maxTokens, 'impact') },
        sessionId,
      )
    case 'refresh':
      return refresh(service, sessionId)
    case 'export':
      return method === POST ? exportWrite(service, sessionId, body, options) : exportPreview(service, sessionId)
    case 'git':
      return gitRoute(service, sessionId)
    default:
      return { ok: false, code: 'not_found', message: 'unknown route' }
  }
}

async function panelTool(service, toolKey, args, sessionId) {
  const result = await service.panelCall(toolKey, args, { sessionId })
  if (!isPlainObject(result) || result.ok !== true) return result
  return { ok: true, data: result }
}

async function refresh(service, sessionId) {
  const result = await service.panelCall('overview', { refresh: true, maxTokens: 500 }, { sessionId })
  if (!isPlainObject(result) || result.ok !== true) return result
  return { ok: true, data: { index: result.index ?? null } }
}

function exportDirOf(service) {
  const dir = service?.cfg?.exportDir
  return typeof dir === 'string' && dir.length > 0 ? dir : 'docs/codebase-intelligence'
}

async function panelState(service, sessionId) {
  const root = service.resolveSessionRoot(sessionId)
  if (typeof root !== 'string' || root.length === 0) {
    return { ok: false, code: 'workspace_unavailable', message: 'no live session workspace yet; open a session in a repository first' }
  }
  const overview = await service.panelCall('overview', { maxTokens: 500 }, { sessionId })
  const outDir = exportDirOf(service)
  let exports = null
  try {
    const plan = await service.exportPreview({ sessionId })
    if (isPlainObject(plan) && plan.ok === true && isPlainObject(plan.payload)) {
      exports = {
        outDir: plan.payload.outDir ?? outDir,
        files: Array.isArray(plan.payload.files) ? plan.payload.files : [],
        stale: plan.payload.stale === true,
        manifestFingerprint: plan.payload.manifestFingerprint ?? null,
      }
    } else {
      exports = { outDir, files: [], stale: true, error: isPlainObject(plan) ? plan.message ?? plan.code ?? 'export unavailable' : 'export unavailable' }
    }
  } catch (error) {
    exports = { outDir, files: [], stale: true, error: messageOf(error) }
  }
  let probe = null
  try {
    probe = await service.bridge?.probe?.()
  } catch {
    probe = null
  }
  return {
    ok: true,
    data: {
      root,
      repo: isPlainObject(overview) && overview.ok === true ? overview.repo ?? null : null,
      entryPoints: isPlainObject(overview) && overview.ok === true ? overview.entryPoints ?? [] : [],
      index: isPlainObject(overview) && overview.ok === true ? overview.index ?? null : null,
      exports,
      git: await gitFacts(root, outDir),
      engine: {
        available: probe?.ready === true,
        pythonVersion: Array.isArray(probe?.version) ? probe.version.join('.') : '',
      },
    },
  }
}

async function exportPreview(service, sessionId) {
  const plan = await service.exportPreview({ sessionId })
  if (!isPlainObject(plan) || plan.ok !== true) return plan
  const payload = isPlainObject(plan.payload) ? plan.payload : {}
  const root = service.resolveSessionRoot(sessionId)
  return {
    ok: true,
    data: {
      outDir: payload.outDir ?? exportDirOf(service),
      files: Array.isArray(payload.files) ? payload.files : [],
      stale: payload.stale === true,
      manifestFingerprint: payload.manifestFingerprint ?? null,
      index: payload.index ?? null,
      git: typeof root === 'string' ? await gitFacts(root, payload.outDir ?? exportDirOf(service)) : null,
    },
  }
}

async function exportWrite(service, sessionId, body, options = {}) {
  if (!isPlainObject(body) || body.confirm !== true) {
    return { ok: false, code: 'invalid_arguments', message: 'writing files requires {"confirm": true}' }
  }
  const result = await service.exportWrite({ sessionId })
  if (!isPlainObject(result) || result.ok !== true) return result
  const payload = isPlainObject(result.payload) ? result.payload : {}
  const root = service.resolveSessionRoot(sessionId)
  const outDir = payload.outDir ?? exportDirOf(service)
  const data = {
    outDir,
    files: Array.isArray(payload.files) ? payload.files : [],
    manifestFingerprint: payload.manifestFingerprint ?? null,
    index: payload.index ?? null,
    git: typeof root === 'string' ? await gitFacts(root, outDir) : null,
  }
  try {
    options.onExported?.(data)
  } catch {
    /* listeners must never break the panel */
  }
  return { ok: true, data }
}

async function gitRoute(service, sessionId) {
  const root = service.resolveSessionRoot(sessionId)
  if (typeof root !== 'string' || root.length === 0) {
    return { ok: false, code: 'workspace_unavailable', message: 'no live session workspace yet' }
  }
  return { ok: true, data: await gitFacts(root, exportDirOf(service)) }
}
