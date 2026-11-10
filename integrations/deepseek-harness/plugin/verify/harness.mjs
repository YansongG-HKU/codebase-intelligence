#!/usr/bin/env node
/**
 * dsh-codebase-intelligence — isolated DSH 0.2.2-rc.1 verification harness.
 *
 * Owns ONE disposable DSH instance for end-to-end verification of the
 * `dsh-codebase-intelligence` plugin, without ever touching the real DSH home,
 * the real desktop app, or the user's repository:
 *
 *   isolated home  F:\dsh插件创造\.tmp\cbi-verify-home        ($DSH_HOME)
 *   profile        p-cbi   (created from the shipped `web` template)
 *   plugin         <profile>\node_modules\dsh-codebase-intelligence  ->  junction to this repo package
 *   instance       dsh web --profile p-cbi --no-open --port 3098 (detached)
 *   logs / state   F:\dsh插件创造\_artifacts\cbi\logs\
 *   repository     F:\QuestionForAI\codebase-intelligence (boot cwd; read-only for the engine)
 *
 * Safety invariants (hard-coded):
 *  - The spawned instance NEVER inherits the ambient DSH_* / ELECTRON_RUN_AS_NODE
 *    environment of the desktop session. Every inherited DSH_* variable is
 *    removed and DSH_HOME is forced to the isolated home; the real home is only
 *    ever read (optional credential copy).
 *  - The junction is removed with unlink() only (never rm -r): a recursive
 *    delete on a Windows junction follows the link into the repository.
 *  - stop() kills exactly the PID recorded in the state file, and only after
 *    proving it is our process (command line contains this CLI + profile p-cbi,
 *    and/or the listening port is owned by that PID). /T kills the small child
 *    tree the web app spawns; a different PID/port is refused, never killed.
 *  - Port 3098 only. Ports 52271 (DSH Web GUI) and 50823 (real desktop app) are
 *    refused at argv-parse time and never contacted.
 *  - Recursive deletion is limited to `.tmp\cbi-verify*` and `_artifacts\cbi`.
 *
 * Usage (run with the bundled Node):
 *   F:\dsh插件创造\_tools\node-v24.22.2-win-x64\node.exe verify\harness.mjs <command> [flags]
 *
 * Commands:
 *   prepare       idempotently materialise home + p-cbi profile + bundle row + junction
 *                 + --dump-config verification (row present, stderr clean) + engine probe fact
 *   dump-config   only the composed profile-tree gate (dsh-codebase-intelligence row)
 *   boot          prepare (unless --skip-prepare) and boot the detached instance;
 *                 prints the token URL. Re-uses a healthy running instance.
 *   up            prepare + boot + health (main entry point)
 *   health        liveness: pid alive + token handshake + app shell + auth fence
 *   status        human summary of the owned instance, logs, activation warnings,
 *                 plugin source snapshot and engine probe
 *   url           print the token URL of the running instance (for Playwright)
 *   stop          stop ONLY the owned instance (identity-checked, tree kill)
 *   restart       stop + boot
 *   logs          print log paths + tails
 *   clean         stop + delete logs/state artifacts (home kept unless --fresh)
 *
 * Flags:
 *   --fresh              wipe the isolated home first (clean baseline)
 *   --restart            stop a running instance before booting
 *   --skip-prepare       boot without re-running prepare
 *   --without-plugin     boot a control profile without the bundle row
 *   --copy-credentials   copy the real home's credentials when missing (read-only source)
 *   --port <n>           only 3098 is accepted
 *   --timeout <ms>       boot/health wait budget (default 90000)
 *   --json               machine-readable result on stdout (harness messages go to stderr)
 *   --help               this text
 *
 * Exit codes: 0 ok, 1 verification/lifecycle failure, 2 usage/safety refusal.
 * Node >= 22, zero dependencies.
 */
import { spawn } from 'node:child_process'
import {
  closeSync,
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readlinkSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// ---------------------------------------------------------------------------
// Fixed paths and configuration
// ---------------------------------------------------------------------------
const HARNESS_DIR = dirname(fileURLToPath(import.meta.url))
const PKG_DIR = resolve(HARNESS_DIR, '..')
const REPO_DIR = resolve(PKG_DIR, '..', '..', '..')
/** DSH tooling root on this machine (bundled Node + dsh CLI). */
const TOOLS_ROOT = process.env.CBI_VERIFY_TOOLS_ROOT ?? 'F:\\dsh插件创造'

const NODE = process.env.CBI_VERIFY_NODE ?? join(TOOLS_ROOT, '_tools', 'node-v24.22.2-win-x64', 'node.exe')
const CLI = process.env.CBI_VERIFY_CLI ?? join(TOOLS_ROOT, '_tools', 'dsh-cli', 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js')
const HOME = process.env.CBI_VERIFY_HOME ?? join(TOOLS_ROOT, '.tmp', 'cbi-verify-home')
const ART = join(TOOLS_ROOT, '_artifacts', 'cbi')
const LOG_DIR = join(ART, 'logs')
/** Real Harness home: read-only, never modified. */
const REAL_HOME = process.env.CBI_REAL_HOME ?? join(homedir(), '.dsh')

const PROFILE_NAME = 'p-cbi'
const PROFILE_DIR = join(HOME, 'profiles', PROFILE_NAME)
const PLUGIN_NAME = 'dsh-codebase-intelligence'
/** The one port this harness may own. */
const PORT = 3098
/** Ports that belong to the user's real applications; never touched. */
const REFUSED_PORTS = Object.freeze([52271, 50823])
const DSH_VERSION = '0.2.2-rc.1'

// ---------------------------------------------------------------------------
// argv
// ---------------------------------------------------------------------------
const USAGE = `dsh-codebase-intelligence verification harness — isolated DSH ${DSH_VERSION} instance

usage: node verify/harness.mjs <prepare|dump-config|boot|up|health|status|url|stop|restart|logs|clean> [flags]

flags: --fresh --restart --skip-prepare --without-plugin --copy-credentials
       --port 3098 --timeout <ms> --json --help`

function parseArgv(argv) {
  const opts = {
    command: null,
    fresh: false,
    restart: false,
    skipPrepare: false,
    withPlugin: true,
    copyCredentials: false,
    port: PORT,
    timeoutMs: 90_000,
    json: false,
    help: false,
  }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--help' || arg === '-h') opts.help = true
    else if (arg === '--fresh') opts.fresh = true
    else if (arg === '--restart') opts.restart = true
    else if (arg === '--skip-prepare') opts.skipPrepare = true
    else if (arg === '--without-plugin') opts.withPlugin = false
    else if (arg === '--copy-credentials') opts.copyCredentials = true
    else if (arg === '--json') opts.json = true
    else if (arg === '--port' || arg === '--timeout') {
      const value = Number(argv[++i])
      if (!Number.isInteger(value) || value <= 0) throw usageError(`--${arg.slice(2)} needs a positive integer`)
      if (arg === '--port') opts.port = value
      else opts.timeoutMs = value
    } else if (arg.startsWith('--port=') || arg.startsWith('--timeout=')) {
      const [flag, raw] = arg.split('=')
      const value = Number(raw)
      if (!Number.isInteger(value) || value <= 0) throw usageError(`${flag} needs a positive integer`)
      if (flag === '--port') opts.port = value
      else opts.timeoutMs = value
    } else if (arg.startsWith('-')) throw usageError(`unknown flag ${arg}`)
    else if (opts.command === null) opts.command = arg
    else throw usageError(`unexpected argument ${arg}`)
  }
  if (opts.command === null) opts.command = 'up'
  assertSafePort(opts.port)
  return opts
}

/** Refuse every port except the harness's own; the real apps are never operated on. */
function assertSafePort(port) {
  if (REFUSED_PORTS.includes(port)) throw usageError(`refusing the real application port ${port}`)
  if (port !== PORT) throw usageError(`this harness owns port ${PORT} only (got ${port})`)
}

class HarnessError extends Error {
  constructor(message, details) {
    super(message)
    this.name = 'HarnessError'
    this.details = details
  }
}
function usageError(message) {
  const error = new HarnessError(`${message}\n\n${USAGE}`)
  error.usage = true
  return error
}

// ---------------------------------------------------------------------------
// logging / output
// ---------------------------------------------------------------------------
let JSON_MODE = false
function log(message) {
  const line = `[harness] ${message}`
  if (JSON_MODE) process.stderr.write(`${line}\n`)
  else console.log(line)
}
function emit(result) {
  if (JSON_MODE) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  } else if (result && typeof result === 'object') {
    const summary = result.summary ?? summarize(result)
    if (summary) console.log(summary)
  }
  return result
}
function summarize(result) {
  const bits = []
  if (result.ok !== undefined) bits.push(result.ok ? 'OK' : 'FAIL')
  if (result.pid) bits.push(`pid=${result.pid}`)
  if (result.port) bits.push(`port=${result.port}`)
  if (result.url) bits.push(result.url)
  if (result.state?.url) bits.push(result.state.url)
  if (result.home) bits.push(`home=${result.home}`)
  if (result.dumpConfig) bits.push(`dump-config=${result.dumpConfig.ok ? 'OK' : 'FAIL'} (${result.dumpConfig.lines} lines, warnings=${result.dumpConfig.warnings.length})`)
  if (result.pluginFiles) bits.push(`plugin(index=${result.pluginFiles.indexJs},patch=${result.pluginFiles.patch},lib=${result.pluginFiles.libFiles.length})`)
  if (result.engineProbe) bits.push(`engine=${result.engineProbe.available ? 'available' : 'missing'}`)
  return bits.join(' ')
}

// ---------------------------------------------------------------------------
// small fs/json helpers
// ---------------------------------------------------------------------------
function ensureDir(path) {
  mkdirSync(path, { recursive: true })
}
function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'))
}
function readJsonSafe(path) {
  try {
    return readJson(path)
  } catch {
    return null
  }
}
function writeJson(path, value) {
  ensureDir(dirname(path))
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
}
function fileBytes(path) {
  try {
    return statSync(path).size
  } catch {
    return null
  }
}
function tailText(path, lines = 40) {
  if (!existsSync(path)) return ''
  const text = readFileSync(path, 'utf8')
  const all = text.split(/\r?\n/)
  return all.slice(-lines).join('\n').trimEnd()
}
function stamp() {
  const now = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}`
}

// ---------------------------------------------------------------------------
// process spawning
// ---------------------------------------------------------------------------
/**
 * The tool shell runs with the real desktop app's environment
 * (DSH_HOME=C:\Users\13645\.dsh, DSH_PROFILE=desktop, DSH_WEB_URL=...). None of
 * it may leak into the isolated instance.
 */
function isolatedEnv() {
  const env = {}
  for (const [key, value] of Object.entries(process.env)) {
    if (/^DSH_/i.test(key)) continue
    if (key.toUpperCase() === 'ELECTRON_RUN_AS_NODE') continue
    env[key] = value
  }
  env.DSH_HOME = HOME
  const nodeDir = dirname(NODE)
  env.PATH = `${nodeDir};${env.PATH ?? env.Path ?? ''}`
  return env
}

/** Run a process to completion, capturing bounded stdout/stderr. */
function run(file, args, { cwd = REPO_DIR, env = isolatedEnv(), timeoutMs = 120_000 } = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    const started = Date.now()
    let child
    try {
      child = spawn(file, args, { cwd, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
    } catch (error) {
      rejectPromise(new HarnessError(`failed to spawn ${file}: ${error.message}`))
      return
    }
    let stdout = ''
    let stderr = ''
    let timedOut = false
    let settled = false
    const timer = setTimeout(() => {
      timedOut = true
      killTree(child.pid)
    }, timeoutMs)
    child.stdout?.setEncoding('utf8')
    child.stderr?.setEncoding('utf8')
    child.stdout?.on('data', (chunk) => {
      if (stdout.length < 8 * 1024 * 1024) stdout += chunk
    })
    child.stderr?.on('data', (chunk) => {
      if (stderr.length < 8 * 1024 * 1024) stderr += chunk
    })
    child.on('error', (error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      rejectPromise(new HarnessError(`failed to spawn ${file}: ${error.message}`))
    })
    child.on('close', (code, signal) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolvePromise({
        code,
        signal,
        stdout,
        stderr,
        timedOut,
        durationMs: Date.now() - started,
        command: [file, ...args].join(' '),
      })
    })
  })
}
function runDsh(args, opts = {}) {
  return run(NODE, [CLI, ...args], { cwd: REPO_DIR, timeoutMs: 180_000, ...opts })
}

function killTree(pid) {
  if (!pid) return
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }).unref()
    } else {
      process.kill(pid, 'SIGKILL')
    }
  } catch {
    /* best effort */
  }
}
function isAlive(pid) {
  if (!pid) return false
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    return error.code === 'EPERM'
  }
}
/** Windows command line of a PID (null when unavailable). */
async function cmdLineOf(pid) {
  const filter = `ProcessId=${Number(pid)}`
  const script = `$p = Get-CimInstance Win32_Process -Filter '${filter}' -ErrorAction SilentlyContinue; if ($p) { $p.CommandLine }`
  try {
    const result = await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], { timeoutMs: 20_000 })
    const line = result.stdout.trim().split(/\r?\n/).filter(Boolean).pop() ?? ''
    return line || null
  } catch {
    return null
  }
}
/** PID listening on a TCP local port (null when nobody listens). */
async function portOwner(port) {
  let netstat
  try {
    netstat = await run('netstat', ['-ano', '-p', 'tcp'], { timeoutMs: 20_000 })
  } catch {
    return null
  }
  for (const line of netstat.stdout.split(/\r?\n/)) {
    // "  TCP    127.0.0.1:3098    0.0.0.0:0    LISTENING    108248"
    const match = line.match(/^\s*TCP\s+(\S+):(\d+)\s+(\S+)\s+(\S+)\s+(\d+)\s*$/)
    if (!match) continue
    const localPort = Number(match[2])
    const remote = match[3]
    const state = match[4].toUpperCase()
    if (localPort !== Number(port)) continue
    if (!state.includes('LISTEN')) continue
    if (!/:(0|\[::\]|0\.0\.0\.0)$/.test(remote)) continue
    return Number(match[5]) || null
  }
  return null
}

// ---------------------------------------------------------------------------
// HTTP helpers (built-in fetch; zero deps)
// ---------------------------------------------------------------------------
async function httpGet(url, { timeoutMs = 10_000, headers = {}, redirect = 'manual' } = {}) {
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers,
      redirect,
      signal: AbortSignal.timeout(timeoutMs),
    })
    const body = await response.text()
    return {
      ok: true,
      status: response.status,
      body,
      headers: Object.fromEntries(response.headers.entries()),
      setCookies: typeof response.headers.getSetCookie === 'function' ? response.headers.getSetCookie() : [],
      error: null,
    }
  } catch (error) {
    return { ok: false, status: 0, body: '', headers: {}, setCookies: [], error: String(error?.cause?.code ?? error.message ?? error) }
  }
}

/** Extract the `dsh-auth-*` session cookie issued by the token-URL redemption. */
function authCookieOf(response) {
  const candidates = [...(response.setCookies ?? [])]
  const raw = response.headers?.['set-cookie']
  if (raw) candidates.push(raw)
  for (const entry of candidates) {
    const match = String(entry).match(/(dsh-auth-[^=]+=[^;,\s]+)/)
    if (match) return match[1]
  }
  return null
}

// ---------------------------------------------------------------------------
// state / log paths
// ---------------------------------------------------------------------------
const statePath = () => join(LOG_DIR, `instance-${PORT}.json`)
const outLogPath = () => join(LOG_DIR, `web-${PORT}.out.log`)
const errLogPath = () => join(LOG_DIR, `web-${PORT}.err.log`)

function readState() {
  return readJsonSafe(statePath())
}
function writeState(state) {
  writeJson(statePath(), state)
  return state
}

// ---------------------------------------------------------------------------
// prepare: home + profile + bundle row + junction + dump-config
// ---------------------------------------------------------------------------
async function ensureProfile(opts) {
  ensureDir(HOME)
  assertHarnessHome()
  const pkgPath = join(PROFILE_DIR, 'package.json')
  if (existsSync(pkgPath)) return { created: false, profileDir: PROFILE_DIR }
  log(`creating profile ${PROFILE_NAME} from the shipped 'web' template`)
  const result = await runDsh(['--profile', PROFILE_NAME, '--from-default-profile', 'web', '--dump-config'], {
    timeoutMs: Math.max(opts.timeoutMs, 60_000),
  })
  if (result.code !== 0) {
    throw new HarnessError(`profile creation failed (exit ${result.code}): ${result.stderr.trim().slice(0, 4000)}`)
  }
  if (!existsSync(pkgPath)) {
    throw new HarnessError(`profile creation exited 0 but ${pkgPath} is missing`, { stdout: result.stdout.slice(-2000) })
  }
  return { created: true, profileDir: PROFILE_DIR }
}

/** The isolated home must live under the tooling root's `.tmp`, never be the real home. */
function assertHarnessHome() {
  const tmpRoot = resolve(TOOLS_ROOT, '.tmp')
  const home = resolve(HOME)
  const normalized = (value) => value.replace(/\\/gu, '/').toLowerCase()
  if (!(normalized(home).startsWith(`${normalized(tmpRoot)}/`) || normalized(home) === normalized(tmpRoot))) {
    throw new HarnessError(`refusing to use ${home}: the isolated home must live under ${tmpRoot}`, { safety: true })
  }
  if (normalized(home) === normalized(resolve(REAL_HOME))) {
    throw new HarnessError('refusing to use the real DSH home as the isolated home', { safety: true })
  }
}

function ensureBundles({ withPlugin }) {
  const pkgPath = join(PROFILE_DIR, 'package.json')
  const pkg = readJson(pkgPath)
  const bundles = pkg?.dsh?.profile?.bundles
  if (!Array.isArray(bundles)) throw new HarnessError(`unexpected profile package.json shape at ${pkgPath}: dsh.profile.bundles is not an array`)
  const index = bundles.indexOf(PLUGIN_NAME)
  let changed = false
  if (withPlugin && index < 0) {
    bundles.push(PLUGIN_NAME)
    changed = true
  } else if (!withPlugin && index >= 0) {
    bundles.splice(index, 1)
    changed = true
  }
  if (changed) writeFileSync(pkgPath, `${JSON.stringify(pkg, null, 2)}\n`, 'utf8')
  return { changed, bundles, packageJson: pkgPath, hasPlugin: bundles.includes(PLUGIN_NAME) }
}

/**
 * Ensure <profile>\node_modules\dsh-codebase-intelligence is a junction to this
 * repository package. A junction is unlinked, never recursively deleted: rm -r
 * on a Windows junction follows the link into the repository.
 */
function ensureJunction() {
  const link = join(PROFILE_DIR, 'node_modules', PLUGIN_NAME)
  ensureDir(join(PROFILE_DIR, 'node_modules'))
  let state = 'ok'
  if (existsSync(link) || lstatOrNull(link)) {
    const stats = lstatOrNull(link)
    if (!stats?.isSymbolicLink()) {
      throw new HarnessError(
        `refusing to touch ${link}: it exists and is not a junction/symlink (real directory). ` +
          'Remove it manually only after confirming it is not this repository package.',
      )
    }
    let same = false
    try {
      same = normalizePath(realpathSync.native(link)) === normalizePath(realpathSync.native(PKG_DIR))
    } catch {
      same = false
    }
    if (same) return { path: link, target: PKG_DIR, created: false }
    log(`junction points elsewhere (${readlinkSafe(link)}); relinking`)
    unlinkSync(link)
    state = 'relinked'
  }
  symlinkSync(PKG_DIR, link, 'junction')
  const target = readlinkSafe(link)
  log(`junction ${link} -> ${PKG_DIR}`)
  return { path: link, target: PKG_DIR, readlink: target, created: true, state }
}
function lstatOrNull(path) {
  try {
    return lstatSync(path)
  } catch {
    return null
  }
}
function readlinkSafe(path) {
  try {
    return readlinkSync(path)
  } catch {
    return null
  }
}
function normalizePath(path) {
  return String(path).replace(/^\\\\\?\\/, '').replace(/\//g, '\\').toLowerCase()
}

/** Read-only snapshot of which plugin source files exist. */
function pluginFiles() {
  const list = (dir, extensions = null) => {
    try {
      return readdirSync(join(PKG_DIR, dir), { withFileTypes: true })
        .filter((entry) => entry.isFile() && (extensions === null || extensions.some((extension) => entry.name.endsWith(extension))))
        .map((entry) => entry.name)
        .sort()
    } catch {
      return []
    }
  }
  return {
    packageDir: PKG_DIR,
    packageJson: existsSync(join(PKG_DIR, 'package.json')),
    indexJs: existsSync(join(PKG_DIR, 'index.js')),
    patch: existsSync(join(PKG_DIR, 'cordis.patch.yml')),
    libFiles: list('lib', ['.js']),
    scriptFiles: list('scripts', ['.mjs', '.js']),
    testFiles: list('test/unit', ['.mjs', '.js']),
    verify: existsSync(join(PKG_DIR, 'verify', 'harness.mjs')),
  }
}

/**
 * `--dump-config` verification: the composed profile tree must contain the
 * dsh-codebase-intelligence layer with its row and config, and stderr must be
 * empty (a missing or unresolved bundle shows up there as a skip warning).
 */
async function verifyDumpConfig(opts) {
  ensureDir(LOG_DIR)
  const result = await runDsh(['--profile', PROFILE_NAME, '--dump-config'], { timeoutMs: Math.max(opts.timeoutMs, 60_000) })
  const stdout = result.stdout
  const stderr = result.stderr.trim()
  const checks = {
    exitZero: result.code === 0,
    layerHeader: stdout.includes(`# == ${PLUGIN_NAME}`),
    rowId: new RegExp(`^- id: ${PLUGIN_NAME}\\s*$`, 'm').test(stdout),
    rowName: new RegExp(`^\\s+name: ${PLUGIN_NAME}\\s*$`, 'm').test(stdout),
    rowConfig: /indexMaxFileBytes:\s*1048576/.test(stdout) && /promptSection:\s*true/.test(stdout) && /context:\s*2200/.test(stdout),
    stderrClean: stderr === '',
  }
  const warnings = stderr.split(/\r?\n/).filter((line) => line.trim().length > 0)
  const dump = {
    ok: Object.values(checks).every(Boolean),
    checks,
    warnings,
    stderr,
    lines: stdout.split(/\r?\n/).length,
    stdoutPath: join(LOG_DIR, 'dump-config.yml'),
    ranAt: new Date().toISOString(),
    durationMs: result.durationMs,
    command: result.command,
  }
  if (stdout.length > 0) writeFileSync(dump.stdoutPath, stdout, 'utf8')
  writeJson(join(LOG_DIR, 'dump-config.json'), dump)
  if (!dump.ok) {
    log(`dump-config verification FAILED: ${JSON.stringify(checks)} warnings=${JSON.stringify(warnings.slice(0, 6))}`)
  } else {
    log(`dump-config OK (${dump.lines} lines, ${PLUGIN_NAME} row present, stderr clean)`)
  }
  return dump
}

function copyCredentials() {
  const copied = []
  for (const name of ['.credentials.yaml', '.anonymous-user-id']) {
    const source = join(REAL_HOME, name)
    const target = join(HOME, name)
    if (existsSync(source) && !existsSync(target)) {
      copyFileSync(source, target)
      copied.push(name)
    }
  }
  return copied
}

/** Best-effort fact: is a usable Python engine importable for this checkout? Read-only. */
async function engineProbe() {
  const srcDir = join(REPO_DIR, 'src')
  const candidates = [process.env.CBI_VERIFY_PYTHON, 'python', 'python3'].filter((value) => typeof value === 'string' && value.length > 0)
  const attempts = []
  for (const command of candidates) {
    try {
      const result = await run(command, ['-c', 'import sys; import codebase_intelligence.cli; print(sys.version.split()[0])'], {
        cwd: REPO_DIR,
        env: { ...isolatedEnv(), PYTHONPATH: srcDir },
        timeoutMs: 30_000,
      })
      if (result.code === 0) {
        const version = result.stdout.trim().split(/\r?\n/).pop() ?? ''
        return { available: true, command, pythonVersion: version, pythonPath: srcDir }
      }
      attempts.push({ command, error: (result.stderr.trim().split(/\r?\n/).pop() ?? `exit ${result.code}`).slice(0, 200) })
    } catch (error) {
      attempts.push({ command, error: String(error.message ?? error).slice(0, 200) })
    }
  }
  return { available: false, pythonPath: srcDir, attempts }
}

async function prepare(opts) {
  ensureDir(ART)
  ensureDir(LOG_DIR)
  ensureDir(HOME)
  assertHarnessHome()
  if (opts.fresh) {
    log(`--fresh: wiping isolated home ${HOME}`)
    await stop(opts, { quiet: true })
    assertOwnPath(HOME)
    rmSync(HOME, { recursive: true, force: true })
    ensureDir(HOME)
  }
  const profile = await ensureProfile(opts)
  const bundles = opts.withPlugin ? ensureBundles(opts) : ensureBundles({ withPlugin: false })
  const junction = opts.withPlugin ? ensureJunction() : null
  const copied = opts.copyCredentials ? copyCredentials() : []
  const files = pluginFiles()
  const dump = opts.withPlugin ? await verifyDumpConfig(opts) : null
  const probe = await engineProbe()
  const facts = {
    ok: opts.withPlugin ? Boolean(dump?.ok) : true,
    at: new Date().toISOString(),
    home: HOME,
    repoDir: REPO_DIR,
    profileName: PROFILE_NAME,
    profileDir: PROFILE_DIR,
    withPlugin: opts.withPlugin,
    profileCreated: profile.created,
    bundles,
    junction,
    copiedCredentials: copied,
    pluginFiles: files,
    dumpConfig: dump,
    engineProbe: probe,
    node: NODE,
    cli: CLI,
    dshVersion: DSH_VERSION,
    inheritedEnvScrubbed: true,
    realHomeTouched: false,
  }
  writeJson(join(LOG_DIR, 'prepare.json'), facts)
  return facts
}

/** Full list of paths this harness is allowed to delete recursively. */
function assertOwnPath(path) {
  const tmpRoot = resolve(TOOLS_ROOT, '.tmp')
  const artRoot = resolve(ART)
  const normalized = resolve(path)
  const under = (root) => normalized === root || normalized.startsWith(`${root}\\`) || normalized.startsWith(`${root}/`)
  const allowed = under(tmpRoot) || under(artRoot)
  if (!allowed) throw new HarnessError(`refusing to delete ${normalized}: outside the harness write scope (.tmp / _artifacts/cbi)`, { safety: true })
  if (normalized === tmpRoot || normalized === artRoot) throw new HarnessError(`refusing to delete root ${normalized}`, { safety: true })
  return normalized
}

// ---------------------------------------------------------------------------
// health
// ---------------------------------------------------------------------------
/**
 * The web app authenticates with a 303 + HttpOnly `dsh-auth-*` cookie when the
 * printed token URL is opened; a bare GET / is 401. Reproduce that handshake.
 */
async function healthCheck(state, { timeoutMs = 8000 } = {}) {
  if (!state?.url) return { ok: false, checks: {}, error: 'no token URL in state' }
  if (!isAlive(state.pid)) return { ok: false, checks: {}, error: `pid ${state.pid} is not alive` }
  const base = `http://127.0.0.1:${state.port}`
  const redeem = await httpGet(state.url, { timeoutMs })
  const cookie = authCookieOf(redeem) ?? state.authCookie ?? null
  const shell = cookie
    ? await httpGet(`${base}/`, { timeoutMs, headers: { cookie } })
    : { ok: false, status: 0, body: '', headers: {}, setCookies: [], error: 'no auth cookie' }
  const noToken = await httpGet(`${base}/`, { timeoutMs })
  const titleMatch = shell.body.match(/<title>([^<]*)<\/title>/i)
  const checks = {
    tokenRedeem: redeem.status === 303 || redeem.status === 302 || redeem.status === 200,
    authCookie: Boolean(cookie),
    appShell: shell.status === 200 && Boolean(titleMatch),
    authFence: noToken.status === 401 || noToken.status === 403,
  }
  const ok = checks.tokenRedeem && checks.authCookie && checks.appShell && checks.authFence
  return {
    ok,
    checks,
    redeem: { status: redeem.status, location: redeem.headers.location ?? null },
    authCookie: cookie,
    shell: { status: shell.status, bytes: shell.body.length, title: titleMatch?.[1] ?? null, error: shell.error },
    noToken: { status: noToken.status, error: noToken.error },
  }
}

// ---------------------------------------------------------------------------
// boot / stop
// ---------------------------------------------------------------------------
function archiveLogs() {
  const archived = []
  for (const [path, label] of [
    [outLogPath(), 'out'],
    [errLogPath(), 'err'],
  ]) {
    if (!existsSync(path)) continue
    const target = join(LOG_DIR, `web-${PORT}.${stamp()}.${label}.log`)
    try {
      renameSync(path, target)
      archived.push(target)
    } catch {
      /* log rotation is best effort */
    }
  }
  return archived
}

async function waitForUrl(pid, deadline, outLog) {
  const pattern = new RegExp(`(http://127\\.0\\.0\\.1:${PORT}/\\?token=([A-Za-z0-9._~-]+))`)
  while (Date.now() < deadline) {
    if (!isAlive(pid)) return { exited: true }
    let text = ''
    try {
      text = readFileSync(outLog, 'utf8')
    } catch {
      /* not yet */
    }
    const match = text.match(pattern)
    if (match) return { url: match[1], token: match[2] }
    await sleep(250)
  }
  return { timeout: true }
}
function sleep(ms) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms))
}

async function boot(opts) {
  assertSafePort(opts.port)
  ensureDir(LOG_DIR)
  const existing = readState()
  if (existing && isAlive(existing.pid)) {
    const health = await healthCheck(existing)
    if (health.ok && !opts.restart) {
      existing.status = 'running'
      existing.health = health
      existing.authCookie = health.authCookie
      existing.appTitle = health.shell?.title ?? existing.appTitle ?? null
      existing.lastHealthAt = new Date().toISOString()
      existing.activation = activationWarnings()
      writeState(existing)
      log(`instance already running (pid ${existing.pid}); reusing ${existing.url}`)
      return emit({ ok: true, reused: true, pid: existing.pid, port: existing.port, url: existing.url, state: existing, health })
    }
    log(`stopping existing instance pid ${existing.pid} (restart=${opts.restart})`)
    await stop(opts)
  }
  const facts = opts.skipPrepare ? readJsonSafe(join(LOG_DIR, 'prepare.json')) ?? (await prepare(opts)) : await prepare(opts)
  if (facts && facts.ok === false) log('WARNING: prepare reported dump-config verification failure; boot proceeds so the failure is observable')

  const archived = archiveLogs()
  const outFd = openSync(outLogPath(), 'w')
  const errFd = openSync(errLogPath(), 'w')
  const args = [CLI, '--profile', PROFILE_NAME, '--no-open', '--port', String(PORT)]
  const startedAt = new Date().toISOString()
  let child
  try {
    child = spawn(NODE, args, {
      cwd: REPO_DIR,
      env: isolatedEnv(),
      windowsHide: true,
      detached: true,
      stdio: ['ignore', outFd, errFd],
    })
  } finally {
    closeSync(outFd)
    closeSync(errFd)
  }
  child.unref()
  const pid = child.pid
  if (!pid) throw new HarnessError('spawned instance has no pid')
  const state = writeState({
    status: 'starting',
    pid,
    port: PORT,
    profile: PROFILE_NAME,
    home: HOME,
    repoDir: REPO_DIR,
    node: NODE,
    cli: CLI,
    args,
    startedAt,
    outLog: outLogPath(),
    errLog: errLogPath(),
    archivedLogs: archived,
    url: null,
  })
  log(`booting dsh web (pid ${pid}) on port ${PORT}; logs ${outLogPath()}`)

  const deadline = Date.now() + opts.timeoutMs
  const found = await waitForUrl(pid, deadline, outLogPath())
  if (!found.url) {
    const stderrTail = tailText(errLogPath(), 60)
    const stdoutTail = tailText(outLogPath(), 20)
    state.status = 'failed'
    state.failedAt = new Date().toISOString()
    state.exitCode = child.exitCode
    state.stderrTail = stderrTail
    writeState(state)
    throw new HarnessError(
      found.exited || child.exitCode !== null
        ? `instance exited before printing a URL (exit ${child.exitCode ?? '?'})`
        : `timed out after ${opts.timeoutMs}ms waiting for the token URL`,
      { state, stderrTail, stdoutTail },
    )
  }
  state.status = 'starting'
  state.url = found.url
  state.token = found.token
  writeState(state)
  log('instance printed token URL; waiting for HTTP health')

  let health = null
  while (Date.now() < deadline) {
    health = await healthCheck(state)
    if (health.ok) break
    if (!isAlive(pid)) break
    await sleep(400)
  }
  state.lastHealthAt = new Date().toISOString()
  state.health = health
  if (!health?.ok) {
    state.status = 'failed'
    state.stderrTail = tailText(errLogPath(), 60)
    writeState(state)
    throw new HarnessError(`instance printed a URL but failed health checks: ${JSON.stringify(health?.checks)}`, { state, health })
  }
  state.status = 'running'
  state.readyAt = new Date().toISOString()
  state.readyMs = Date.parse(state.readyAt) - Date.parse(startedAt)
  state.authCookie = health.authCookie
  state.appTitle = health.shell?.title ?? null
  state.activation = activationWarnings()
  writeState(state)
  const result = {
    ok: true,
    reused: false,
    pid,
    port: PORT,
    url: state.url,
    readyMs: state.readyMs,
    health,
    activation: state.activation,
    state,
    prepare: facts,
  }
  writeJson(join(LOG_DIR, 'boot.json'), result)
  log(`instance READY pid=${pid} url=${state.url} (${state.readyMs}ms)`)
  return emit(result)
}

/** Host-side activation warnings from the instance stderr (e.g. failed import). */
function activationWarnings() {
  const text = tailText(errLogPath(), 200)
  const lines = text.split(/\r?\n/).filter((line) => /warn|error|fail|not activate|missing|not found/i.test(line))
  return {
    errBytes: fileBytes(errLogPath()),
    warningLines: lines.slice(0, 12),
    any: lines.length > 0,
  }
}

async function stop(opts, { quiet = false } = {}) {
  assertSafePort(opts.port)
  if (!existsSync(statePath())) {
    const owner = await portOwner(PORT)
    if (owner) {
      throw new HarnessError(
        `no harness state file for port ${PORT}, but PID ${owner} is listening there — refusing to kill a process this harness did not start`,
        { safety: true, owner },
      )
    }
    if (!quiet) log('no instance state found; nothing to stop')
    return { ok: true, stopped: false }
  }
  const state = readState()
  if (!state) throw new HarnessError(`state file ${statePath()} exists but is not valid JSON; refusing to guess at a PID`, { safety: true })
  const pid = state.pid
  if (!isAlive(pid)) {
    state.status = 'stopped'
    state.stoppedAt = state.stoppedAt ?? new Date().toISOString()
    writeState(state)
    if (!quiet) log(`pid ${pid} already gone; state marked stopped`)
    return { ok: true, stopped: false, stale: true, pid }
  }
  // Identity proof: never kill a process this harness did not start.
  const [cmd, owner] = await Promise.all([cmdLineOf(pid), portOwner(PORT)])
  const cmdOk = typeof cmd === 'string' && cmd.includes('dsh') && cmd.includes(`--profile ${PROFILE_NAME}`)
  const portOk = owner === pid
  if (!cmdOk && !portOk) {
    throw new HarnessError(`refusing to kill pid ${pid}: command line / port ownership does not match the harness instance`, {
      safety: true,
      pid,
      cmdLine: cmd,
      portOwner: owner,
    })
  }
  log(`stopping harness instance pid ${pid} (cmdline=${cmdOk}, portOwner=${owner})`)
  killTree(pid)
  const deadline = Date.now() + 15_000
  while (Date.now() < deadline && isAlive(pid)) await sleep(200)
  const stillAlive = isAlive(pid)
  state.status = stillAlive ? 'failed-to-stop' : 'stopped'
  state.stoppedAt = new Date().toISOString()
  state.stopProof = { cmdLineOk: cmdOk, portOwner: owner, killedTree: true }
  writeState(state)
  if (stillAlive) throw new HarnessError(`pid ${pid} still alive after taskkill /T /F`, { state })
  const ownerAfter = await portOwner(PORT)
  if (ownerAfter) log(`WARNING: port ${PORT} still owned by ${ownerAfter} after stop`)
  const result = { ok: true, stopped: true, pid, port: PORT, portFree: ownerAfter === null, state }
  return quiet ? result : emit(result)
}

// ---------------------------------------------------------------------------
// commands
// ---------------------------------------------------------------------------
function assertReady(condition, message, details) {
  if (!condition) throw new HarnessError(message, details)
}

async function requireRunning() {
  const state = readState()
  assertReady(state, `no instance state for port ${PORT}; run 'boot' or 'up' first`)
  assertReady(isAlive(state.pid), `instance pid ${state.pid} is not alive; run 'boot' first`)
  assertReady(state.url, 'instance state has no token URL yet; boot still in progress?')
  return state
}

async function cmdPrepare(opts) {
  const facts = await prepare(opts)
  return emit(facts)
}

async function cmdDumpConfig(opts) {
  const profile = await ensureProfile(opts)
  const bundles = opts.withPlugin ? ensureBundles({ withPlugin: true }) : ensureBundles({ withPlugin: false })
  if (opts.withPlugin) ensureJunction()
  const dump = opts.withPlugin ? await verifyDumpConfig(opts) : null
  const facts = { ok: opts.withPlugin ? Boolean(dump?.ok) : true, profileCreated: profile.created, bundles, dump, pluginFiles: pluginFiles() }
  return emit(facts)
}

async function cmdHealth(opts) {
  const state = await requireRunning()
  const health = await healthCheck(state)
  return emit({ ok: health.ok, pid: state.pid, port: state.port, url: state.url, health, state })
}

async function cmdStatus(opts) {
  const state = readState()
  if (!state) return emit({ ok: false, running: false, port: PORT, error: 'no state file; instance never booted by this harness' })
  const alive = isAlive(state.pid)
  const owner = await portOwner(PORT)
  const health = alive && state.url ? await healthCheck(state) : null
  const status = {
    ok: alive && Boolean(health?.ok),
    running: alive,
    pid: state.pid,
    port: PORT,
    status: state.status,
    url: state.url,
    home: state.home,
    repoDir: state.repoDir,
    profile: state.profile,
    startedAt: state.startedAt,
    readyMs: state.readyMs,
    portOwner: owner,
    portIsOurs: owner === state.pid,
    health,
    activation: activationWarnings(),
    pluginFiles: pluginFiles(),
    engineProbe: await engineProbe(),
    outLog: { path: outLogPath(), bytes: fileBytes(outLogPath()) },
    errLog: { path: errLogPath(), bytes: fileBytes(errLogPath()), tail: tailText(errLogPath(), 12) },
  }
  return emit(status)
}

async function cmdUrl(opts) {
  const state = await requireRunning()
  const health = await healthCheck(state)
  if (!health.ok) throw new HarnessError('instance is running but unhealthy; refusing to hand out its URL', { health })
  if (JSON_MODE) return emit({ ok: true, url: state.url, pid: state.pid, port: PORT })
  process.stdout.write(`${state.url}\n`)
  return { ok: true, url: state.url }
}

async function cmdRestart(opts) {
  await stop(opts, { quiet: true })
  opts.restart = true
  return boot(opts)
}

async function cmdLogs(opts) {
  const out = outLogPath()
  const err = errLogPath()
  const result = {
    ok: true,
    out: { path: out, bytes: fileBytes(out), tail: tailText(out, 20) },
    err: { path: err, bytes: fileBytes(err), tail: tailText(err, 40) },
    state: readState(),
  }
  if (!JSON_MODE) {
    console.log(`--- ${out} (${fileBytes(out) ?? 'missing'} bytes) ---\n${result.out.tail}\n`)
    console.log(`--- ${err} (${fileBytes(err) ?? 'missing'} bytes) ---\n${result.err.tail}\n`)
    return result
  }
  return emit(result)
}

async function cmdClean(opts) {
  const stopped = await stop(opts, { quiet: true })
  assertOwnPath(LOG_DIR)
  rmSync(LOG_DIR, { recursive: true, force: true })
  if (opts.fresh) {
    assertOwnPath(HOME)
    rmSync(HOME, { recursive: true, force: true })
  }
  log(`cleaned verification artifacts (home ${opts.fresh ? 'wiped' : 'kept'})`)
  return emit({ ok: true, stopped, homeWiped: opts.fresh, logDir: LOG_DIR })
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
async function main() {
  let opts
  try {
    opts = parseArgv(process.argv.slice(2))
  } catch (error) {
    console.error(error.message)
    process.exit(error.usage ? 2 : 1)
  }
  JSON_MODE = opts.json
  if (opts.help) {
    console.log(USAGE)
    process.exit(0)
  }
  // Hard guard: ports that belong to the user's real applications are never operated on.
  if (REFUSED_PORTS.includes(opts.port)) {
    console.error(`[harness] refusing to operate on port ${opts.port}`)
    process.exit(2)
  }
  const commands = {
    prepare: cmdPrepare,
    'dump-config': cmdDumpConfig,
    boot,
    up: boot,
    health: cmdHealth,
    status: cmdStatus,
    url: cmdUrl,
    stop: (options) => stop(options),
    restart: cmdRestart,
    logs: cmdLogs,
    clean: cmdClean,
  }
  const handler = commands[opts.command]
  if (!handler) {
    console.error(`unknown command '${opts.command}'\n\n${USAGE}`)
    process.exit(2)
  }
  try {
    const result = await handler(opts)
    process.exit(result && result.ok === false ? 1 : 0)
  } catch (error) {
    const details = error instanceof HarnessError ? error.details : undefined
    const message = `${error instanceof HarnessError ? error.message : error?.stack ?? String(error)}`
    console.error(`[harness] ${opts.command} FAILED: ${message}`)
    if (details) {
      const compact = JSON.stringify(details, (key, value) => (typeof value === 'string' && value.length > 4000 ? `${value.slice(0, 4000)}…` : value), 2)
      if (JSON_MODE) process.stdout.write(`${JSON.stringify({ ok: false, command: opts.command, error: message, details }, null, 2)}\n`)
      else console.error(compact)
    } else if (JSON_MODE) {
      process.stdout.write(`${JSON.stringify({ ok: false, command: opts.command, error: message }, null, 2)}\n`)
    }
    process.exit(error?.usage ? 2 : 1)
  }
}

await main()
