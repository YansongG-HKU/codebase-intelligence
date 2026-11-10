/**
 * The six model-facing tool definitions.
 *
 * Definitions are raw JSON objects shaped like the Harness `ToolDefinition`:
 * a static JSON-Schema `parameters` object (no dynamic values, no defaults —
 * the effective budget comes from config at execute time), an `output`
 * projector that renders one compact JSON text block, and an `execute`
 * function whose result is always lossless JSON and never a thrown error.
 *
 * The engine JSON object is the tool value verbatim: the plugin adds no
 * timestamps, cache flags, durations or paths, so two identical calls produce
 * byte-identical output.
 *
 * @module dsh-codebase-intelligence/tools
 */

import { MAX_TOKENS_LIMIT, MIN_MAX_TOKENS, TOOL_IDS, TOOL_KEYS } from './config.js'
import { messageOf } from './util.js'

/** Shared output projector: one JSON text block, nothing else. */
const OUTPUT = Object.freeze({
  schema: { type: 'object', additionalProperties: true },
  render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
})

/** The repair hint attached to an unexpected internal failure. */
const INTERNAL_REPAIR = Object.freeze({
  action: 'retry',
  label: 'Retry once; if it persists, call codebase_overview to check the workspace',
  detail: 'The plugin returns a structured error envelope instead of throwing.',
})

const INTEGER_MAX_TOKENS = Object.freeze({
  type: 'integer',
  minimum: MIN_MAX_TOKENS,
  maximum: MAX_TOKENS_LIMIT,
  description: 'Token budget for this response, clamped to 200-8000. Omit to use the configured per-tool default.',
})

const BOOLEAN_REFRESH = Object.freeze({
  type: 'boolean',
  description: 'Force a fresh index build instead of reusing the cached index.',
})

const STRING_FOCUS = Object.freeze({
  type: 'string',
  description: 'Repository-relative path prefix to focus the map, e.g. "src/app".',
})

const STRING_QUERY = Object.freeze({
  type: 'string',
  description: 'Lexical query matched against paths, symbol names, signatures and docstrings.',
})

const STRING_TARGET = Object.freeze({
  type: 'string',
  description: 'Repository-relative file path or symbol id to inspect.',
})

const STRING_DIRECTION = Object.freeze({
  type: 'string',
  enum: Object.freeze(['both', 'imports', 'dependents']),
  description: 'both (default), imports for outgoing edges, dependents for incoming edges.',
})

const INTEGER_DEPTH = Object.freeze({
  type: 'integer',
  minimum: 1,
  maximum: 5,
  description: 'Maximum graph distance to traverse (1-5; default 1).',
})

const STRING_TASK = Object.freeze({
  type: 'string',
  description: 'The task or question the context pack should serve.',
})

const STRING_PATH_PREFIX = Object.freeze({
  type: 'string',
  description: 'Optional repository-relative path prefix to restrict the context pack.',
})

const ARRAY_FILES = Object.freeze({
  type: 'array',
  items: { type: 'string' },
  maxItems: 50,
  description: 'Repository-relative file paths whose dependents and references should be analyzed.',
})

const ARRAY_SYMBOLS = Object.freeze({
  type: 'array',
  items: { type: 'string' },
  maxItems: 100,
  description: 'Symbol ids or names whose references should be analyzed.',
})

/** Description text per tool: short, stable, part of the measured token footprint. */
const DESCRIPTIONS = Object.freeze({
  overview:
    'Summarize the session workspace: languages, file/symbol counts, top directories and candidate entry points. ' +
    'Read-only and bounded; call it once before narrower structure questions.',
  map:
    'Return a compact structural map of files and important symbols, optionally focused on one repository-relative ' +
    'path prefix. Symbols are declarations, not full source semantics.',
  search:
    'Search files and symbols by lexical match over paths, names, signatures and docstrings. Each result cites its ' +
    'repository-relative path and line; use it to find a valid target for the other tools.',
  dependencies:
    'Show imports, dependents or both for a file or symbol, one to five hops deep. Every edge carries its resolution ' +
    'status: unresolved and ambiguous edges stay labelled and are never reported as confirmed dependencies.',
  context:
    'Build a task-focused context pack: ranked, bounded definition excerpts with path:line citations plus explicit ' +
    'omissions, measured against the token budget. Read the cited source before editing it.',
  impact:
    'Preview files and symbols likely affected by changing the given files or symbols, with confidence and reason ' +
    'labels. Impact is conservative: low-confidence name matches are labelled, not promoted.',
})

/**
 * Build the enabled tool definitions for one Agent.
 *
 * @param {{
 *   agent?: object | null,
 *   cfg: object,
 *   service: {call: Function},
 *   log?: {warn?: Function} | null,
 * }} options
 * @returns {object[]} Harness ToolDefinition objects
 */
export function createTools({ agent = null, cfg, service, log = null } = {}) {
  const definitions = []
  const enabled = (key) => cfg?.tools?.[key] !== false

  /** Wrap one handler: never throw, always return lossless JSON. */
  const handler = (toolKey) => async (args, exec) => {
    try {
      if (service === null || typeof service?.call !== 'function') {
        return { ok: false, code: 'failed', message: 'the codebase engine service is not available', repair: INTERNAL_REPAIR }
      }
      const value = await service.call(toolKey, args ?? {}, { agent, signal: exec?.signal })
      return lossless(value)
    } catch (error) {
      log?.warn?.(`tool ${TOOL_IDS[toolKey]} failed: ${messageOf(error)}`)
      return { ok: false, code: 'failed', message: 'the tool failed unexpectedly', repair: INTERNAL_REPAIR }
    }
  }

  const define = ({ key, properties, required = null }) => {
    const parameters = { type: 'object', properties: { ...properties }, additionalProperties: false }
    if (Array.isArray(required) && required.length > 0) parameters.required = required
    definitions.push({
      name: TOOL_IDS[key],
      description: DESCRIPTIONS[key],
      parameters,
      output: OUTPUT,
      execute: handler(key),
    })
  }

  if (enabled('overview')) {
    define({ key: 'overview', properties: { maxTokens: INTEGER_MAX_TOKENS, refresh: BOOLEAN_REFRESH } })
  }
  if (enabled('map')) {
    define({ key: 'map', properties: { focus: STRING_FOCUS, maxTokens: INTEGER_MAX_TOKENS, refresh: BOOLEAN_REFRESH } })
  }
  if (enabled('search')) {
    define({ key: 'search', properties: { query: STRING_QUERY, maxTokens: INTEGER_MAX_TOKENS, refresh: BOOLEAN_REFRESH }, required: ['query'] })
  }
  if (enabled('dependencies')) {
    define({
      key: 'dependencies',
      properties: {
        target: STRING_TARGET,
        direction: STRING_DIRECTION,
        depth: INTEGER_DEPTH,
        maxTokens: INTEGER_MAX_TOKENS,
        refresh: BOOLEAN_REFRESH,
      },
      required: ['target'],
    })
  }
  if (enabled('context')) {
    define({
      key: 'context',
      properties: {
        task: STRING_TASK,
        pathPrefix: STRING_PATH_PREFIX,
        maxTokens: INTEGER_MAX_TOKENS,
        refresh: BOOLEAN_REFRESH,
      },
      required: ['task'],
    })
  }
  if (enabled('impact')) {
    define({
      key: 'impact',
      properties: {
        files: ARRAY_FILES,
        symbols: ARRAY_SYMBOLS,
        maxTokens: INTEGER_MAX_TOKENS,
        refresh: BOOLEAN_REFRESH,
      },
    })
  }
  return definitions
}

/** The six registered tool names, in registration order. */
export const TOOL_NAMES = Object.freeze(TOOL_KEYS.map((key) => TOOL_IDS[key]))

/** Ensure a value survives the Harness lossless-JSON output check. */
function lossless(value) {
  if (value === undefined) return null
  try {
    return JSON.parse(JSON.stringify(value))
  } catch {
    return { ok: false, code: 'failed', message: 'the tool output was not serializable', repair: INTERNAL_REPAIR }
  }
}
