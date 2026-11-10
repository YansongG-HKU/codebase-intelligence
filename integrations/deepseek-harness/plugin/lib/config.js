/**
 * Configuration resolution for `dsh-codebase-intelligence`.
 *
 * The loader row in `cordis.patch.yml` is the only user-facing config surface.
 * `resolveConfig` is deliberately total: a malformed row degrades to defaults
 * and records a bounded message in `errors` (the plugin logs it once), because
 * a bad config must never prevent the tools from registering or an Agent from
 * starting. Values are plain JSON scalars — the row may also be edited by hand.
 *
 * @module dsh-codebase-intelligence/config
 */

import { homedir } from 'node:os'
import { join } from 'node:path'

/** Tool keys (short names used by config/schemas) mapped to registered tool names. */
export const TOOL_IDS = Object.freeze({
  overview: 'codebase_overview',
  map: 'codebase_map',
  search: 'codebase_search',
  dependencies: 'codebase_dependencies',
  context: 'codebase_context',
  impact: 'codebase_impact',
})

/** Short tool keys in registration order. */
export const TOOL_KEYS = Object.freeze(Object.keys(TOOL_IDS))

/** SPEC §4 default budgets per tool. */
export const DEFAULT_MAX_TOKENS = Object.freeze({
  overview: 900,
  map: 1600,
  search: 1200,
  dependencies: 1200,
  context: 2200,
  impact: 1200,
})

/** Engine hard cap per tool (docs/SPEC.md §4). */
export const MAX_TOKENS_LIMIT = 8000

/**
 * Plugin-side lower clamp for `maxTokens` (stricter than the engine's 64, so a
 * tool result is never a useless fragment). Documented in docs/DSH_PLUGIN.md.
 */
export const MIN_MAX_TOKENS = 200

/** Default engine timeout (docs/SPEC.md §13). */
export const DEFAULT_TIMEOUT_MS = 120_000

/** SPEC §5 scanner default; exposed here so the CLI receives an explicit value. */
export const DEFAULT_MAX_FILE_BYTES = 1_048_576

/** Default generation directory for `cbi export` (docs/PANEL_CONTRACT.md §1). */
export const DEFAULT_EXPORT_DIR = 'docs/codebase-intelligence'

/** Absolute fallback data directory name under the Harness home. */
export const DATA_DIR_NAME = 'codebase-intelligence'

/**
 * Per-command flag mapping used by the bridge and documented in docs/DSH_PLUGIN.md.
 * Kept here (not in bridge.js) so the footprint/scripts and tests share one table.
 */
export const TOOL_CLI_COMMAND = Object.freeze({
  overview: 'overview',
  map: 'map',
  search: 'search',
  dependencies: 'dependencies',
  context: 'context',
  impact: 'impact',
})

/**
 * Resolve the effective plugin config from a loader row.
 *
 * @param {unknown} rowConfig the loader row config (may be missing/malformed)
 * @param {{env?: Record<string, string | undefined>, home?: string}} [options]
 * @returns {{
 *   pythonPath: string | null,
 *   corePath: string | null,
 *   dataDir: string,
 *   timeoutMs: number,
 *   indexMaxFileBytes: number,
 *   maxTokens: Record<string, number>,
 *   tools: Record<string, boolean>,
 *   promptSection: boolean,
 *   errors: string[],
 * }}
 */
export function resolveConfig(rowConfig, options = {}) {
  const env = options.env ?? process.env
  const home = typeof options.home === 'string' && options.home.length > 0 ? options.home : homedir()
  const row = isRecord(rowConfig) ? rowConfig : {}
  const errors = []
  const dataHome = nonEmptyString(env.DSH_HOME) ?? join(home, '.dsh')

  const maxTokens = {}
  const rawMaxTokens = isRecord(row.maxTokens) ? row.maxTokens : {}
  for (const key of TOOL_KEYS) {
    const fallback = DEFAULT_MAX_TOKENS[key]
    const raw = rawMaxTokens[key]
    if (raw === undefined || raw === null) {
      maxTokens[key] = fallback
      continue
    }
    const value = clampInteger(raw, MIN_MAX_TOKENS, MAX_TOKENS_LIMIT, null)
    if (value === null) {
      errors.push(`config.maxTokens.${key} is not an integer; using ${fallback}`)
      maxTokens[key] = fallback
    } else {
      maxTokens[key] = value
    }
  }

  const tools = {}
  const rawTools = isRecord(row.tools) ? row.tools : {}
  for (const key of TOOL_KEYS) {
    const raw = rawTools[key]
    tools[key] = raw === false ? false : true
  }

  const promptSection = row.promptSection === false ? false : true

  let pythonPath = nonEmptyString(row.pythonPath)
  let corePath = nonEmptyString(row.corePath)
  let dataDir = nonEmptyString(row.dataDir)
  if (row.dataDir !== undefined && row.dataDir !== '' && dataDir === null) {
    errors.push('config.dataDir is not a non-empty string; using the default data directory')
  }
  if (dataDir === null) dataDir = join(dataHome, DATA_DIR_NAME)

  const timeoutRaw = clampInteger(row.timeoutMs, 5_000, 600_000, DEFAULT_TIMEOUT_MS)
  if (row.timeoutMs !== undefined && row.timeoutMs !== null && timeoutRaw === null) {
    errors.push(`config.timeoutMs is not an integer between 5000 and 600000; using ${DEFAULT_TIMEOUT_MS}`)
  }
  const timeoutMs = timeoutRaw ?? DEFAULT_TIMEOUT_MS

  const maxFileRaw = clampInteger(row.indexMaxFileBytes, 1_024, 64 * 1_048_576, DEFAULT_MAX_FILE_BYTES)
  if (row.indexMaxFileBytes !== undefined && row.indexMaxFileBytes !== null && maxFileRaw === null) {
    errors.push(`config.indexMaxFileBytes is not an integer between 1024 and 67108864; using ${DEFAULT_MAX_FILE_BYTES}`)
  }
  const indexMaxFileBytes = maxFileRaw ?? DEFAULT_MAX_FILE_BYTES

  const panelEnabled = row.panel === false ? false : true

  let exportDir = DEFAULT_EXPORT_DIR
  if (row.exportDir !== undefined && row.exportDir !== null && row.exportDir !== '') {
    const candidate = typeof row.exportDir === 'string' ? row.exportDir.trim().replace(/\\/gu, '/') : ''
    if (candidate.length === 0 || isAbsoluteLike(candidate) || candidate.split('/').includes('..')) {
      errors.push(`config.exportDir must be a relative path inside the workspace; using ${DEFAULT_EXPORT_DIR}`)
    } else {
      exportDir = candidate.replace(/^\.\//u, '').replace(/\/+$/u, '')
    }
  }

  return {
    pythonPath,
    corePath,
    dataDir,
    timeoutMs,
    indexMaxFileBytes,
    maxTokens,
    tools,
    promptSection,
    panelEnabled,
    exportDir,
    errors,
  }
}

/** True for POSIX-absolute, Windows drive-letter or UNC-looking paths. */
function isAbsoluteLike(value) {
  return value.startsWith('/') || value.startsWith('~') || /^[A-Za-z]:/u.test(value) || value.startsWith('//')
}

/**
 * Effective `maxTokens` for one tool call: the caller's value clamped to the
 * documented range, else the config default for that tool.
 *
 * @param {ReturnType<typeof resolveConfig>} cfg resolved config
 * @param {string} toolKey short tool key
 * @param {unknown} requested caller value from the tool argument
 * @returns {number} clamped integer budget
 */
export function resolveMaxTokens(cfg, toolKey, requested) {
  const fallback = cfg?.maxTokens?.[toolKey] ?? DEFAULT_MAX_TOKENS[toolKey] ?? 1200
  if (requested === undefined || requested === null) return fallback
  const coerced = typeof requested === 'number' ? requested : Number(requested)
  if (!Number.isFinite(coerced)) return fallback
  return Math.min(MAX_TOKENS_LIMIT, Math.max(MIN_MAX_TOKENS, Math.trunc(coerced)))
}

/** Whether a tool key is enabled by config. */
export function isToolEnabled(cfg, toolKey) {
  return cfg?.tools?.[toolKey] !== false
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : null
}

function clampInteger(value, minimum, maximum, fallback) {
  if (value === undefined || value === null) return fallback
  const number = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(number) || Math.trunc(number) !== number) return null
  return Math.min(maximum, Math.max(minimum, number))
}
