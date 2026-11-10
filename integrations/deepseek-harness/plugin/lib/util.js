/**
 * Small dependency-free helpers shared by the bridge, service and tools.
 *
 * The token estimate is the JavaScript mirror of the engine's
 * `util.estimate_tokens` ("chars4-wide-v1", docs/SPEC.md §4): every 4 ASCII
 * characters count as one token, every non-ASCII character as one token, and
 * the total is rounded up with a floor of 1 for non-empty input. It is an
 * estimate for budget planning, not a tokenizer, and is never applied to the
 * unprompted full payload a caller did not ask to measure.
 */

import { createHash } from 'node:crypto'

/** Message text of an unknown thrown value. */
export function messageOf(error) {
  if (error instanceof Error) return error.message
  return String(error)
}

/** First non-empty line of `text`, bounded (used for diagnostics only). */
export function firstLine(text, max = 500) {
  const value = String(text ?? '').trim()
  if (value.length === 0) return ''
  const line = value.split(/\r?\n/u).find((item) => item.trim().length > 0) ?? value
  return line.trim().slice(0, max)
}

/** Plain-object guard (arrays and null are not plain objects). */
export function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** Lowercase hex SHA-256 of a UTF-8 string. */
export function sha256Hex(text) {
  return createHash('sha256').update(String(text), 'utf8').digest('hex')
}

/** UTF-8 byte length of a string (what a model-facing payload costs on the wire). */
export function utf8Bytes(text) {
  return Buffer.byteLength(String(text ?? ''), 'utf8')
}

/**
 * `chars4-wide-v1` token estimate for a string.
 *
 * @param {string} text model-facing text
 * @returns {number} estimated tokens (0 for empty, at least 1 otherwise)
 */
export function estimateTokens(text) {
  if (typeof text !== 'string' || text.length === 0) return 0
  let ascii = 0
  let nonAscii = 0
  for (const char of text) {
    if (char.codePointAt(0) < 0x80) ascii += 1
    else nonAscii += 1
  }
  return Math.max(1, Math.ceil(ascii / 4 + nonAscii))
}

/** JSON-safe deep clone; `undefined` stays `undefined`. */
export function deepClone(value) {
  if (value === undefined) return undefined
  return JSON.parse(JSON.stringify(value))
}

/** Resolve after `ms` milliseconds. */
export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Deterministic canonical JSON (sorted keys, compact separators).
 *
 * Used for memo cache keys and footprint measurement only — never to reorder
 * an engine payload that is returned to a model.
 *
 * @param {unknown} value JSON-compatible value
 * @returns {string} canonical JSON text
 */
export function canonicalJson(value) {
  return JSON.stringify(sortValue(value))
}

function sortValue(value) {
  if (Array.isArray(value)) return value.map((item) => sortValue(item))
  if (value !== null && typeof value === 'object') {
    const out = {}
    for (const key of Object.keys(value).sort()) out[key] = sortValue(value[key])
    return out
  }
  return value
}
