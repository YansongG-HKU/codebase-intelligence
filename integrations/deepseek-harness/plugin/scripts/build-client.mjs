/**
 * dsh-codebase-intelligence — rebuild the client artifact.
 *
 * The shipped client must stay one dependency-free classic script that the DSH
 * module loader can evaluate directly, so the readable sources in
 * `src/client/` are concatenated in filename order (00-head … 05-apply; the
 * loader wrapper opens in 00-head and closes in 05-apply). The zh/en
 * dictionaries are generated from the single `TEXT_ENTRIES` block in
 * 00-head.js into `locale/zh.json` and `locale/en.json`.
 *
 * Usage: node scripts/build-client.mjs [--check]
 */

import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const sourceDir = join(root, 'src', 'client')
const clientPath = join(root, 'client.js')
const localeDir = join(root, 'locale')

/** The shipped bundle stays well under 150 KiB (PANEL_CONTRACT §4). */
const MAX_BUNDLE_BYTES = 150 * 1024
/** Marker comments that delimit the dictionary source of truth. */
const TEXT_BEGIN = '/* cbi-text-entries:begin */'
const TEXT_END = '/* cbi-text-entries:end */'
/** Locale files generated from `TEXT_ENTRIES`. */
const LOCALES = ['zh', 'en']

const check = process.argv.includes('--check')
const fragments = readdirSync(sourceDir)
  .filter((name) => name.endsWith('.js'))
  .sort()
if (fragments.length === 0) throw new Error('no client fragments found in ' + sourceDir)

const source = fragments.map((name) => readFileSync(join(sourceDir, name), 'utf8')).join('\n')
const sourceBytes = Buffer.byteLength(source, 'utf8')
if (sourceBytes > MAX_BUNDLE_BYTES) {
  throw new Error(
    'client bundle is ' + sourceBytes + ' bytes; the contract caps it at ' + MAX_BUNDLE_BYTES + ' bytes',
  )
}

/** Normalize line endings and trailing whitespace so builds are OS-stable. */
const normalize = (text) => String(text).replace(/\r\n/g, '\n').replace(/\n+$/u, '') + '\n'

/* ---------------------------------------------------------------------- */
/* Dictionaries                                                           */
/* ---------------------------------------------------------------------- */

/** Evaluate the marked `const TEXT_ENTRIES = [...]` block without a browser. */
export function extractTextEntries(text) {
  const begin = text.indexOf(TEXT_BEGIN)
  const end = text.indexOf(TEXT_END)
  if (begin < 0 || end < 0 || end <= begin) {
    throw new Error('TEXT_ENTRIES markers are missing from the client sources')
  }
  const block = text.slice(begin + TEXT_BEGIN.length, end)
  // eslint-disable-next-line no-new-func -- the block is our own literal source
  const entries = new Function(block + '\nreturn TEXT_ENTRIES')()
  if (!Array.isArray(entries) || entries.length === 0) {
    throw new Error('TEXT_ENTRIES must be a non-empty array')
  }
  const seen = new Set()
  const normalized = entries.map((row, index) => {
    if (!Array.isArray(row) || row.length !== 3) {
      throw new Error(`TEXT_ENTRIES row ${index} must be [key, zh, en]`)
    }
    const [key, zh, en] = row
    if (typeof key !== 'string' || !/^[a-z][a-zA-Z0-9]*(\.[a-zA-Z0-9]+)*$/u.test(key)) {
      throw new Error(`TEXT_ENTRIES row ${index} has an invalid key: ${JSON.stringify(key)}`)
    }
    if (seen.has(key)) throw new Error(`TEXT_ENTRIES contains a duplicate key: ${key}`)
    seen.add(key)
    for (const value of [zh, en]) {
      if (typeof value !== 'string' || value.length === 0) {
        throw new Error(`TEXT_ENTRIES "${key}" must have non-empty zh and en text`)
      }
      if (value.includes('\u200b') || value.includes('\ufeff')) {
        throw new Error(`TEXT_ENTRIES "${key}" contains a zero-width/BOM character`)
      }
    }
    return [key, zh, en]
  })
  return normalized
}

/** Build the per-locale flat dictionaries from the paired rows. */
export function dictionariesOf(entries) {
  const dictionaries = {}
  for (const locale of LOCALES) dictionaries[locale] = {}
  for (const [key, zh, en] of entries) {
    dictionaries.zh[key] = zh
    dictionaries.en[key] = en
  }
  return dictionaries
}

export function localeJson(dictionary) {
  return JSON.stringify(dictionary, null, 2) + '\n'
}

/* ---------------------------------------------------------------------- */
/* Build / check                                                          */
/* ---------------------------------------------------------------------- */

const entries = extractTextEntries(source)
const dictionaries = dictionariesOf(entries)
const outputs = [
  { path: clientPath, content: normalize(source), label: 'client.js' },
  ...LOCALES.map((locale) => ({
    path: join(localeDir, `${locale}.json`),
    content: localeJson(dictionaries[locale]),
    label: `locale/${locale}.json`,
  })),
]

const readOrEmpty = (path) => {
  try {
    return readFileSync(path, 'utf8')
  } catch {
    return ''
  }
}

if (check) {
  const stale = []
  for (const output of outputs) {
    if (normalize(readOrEmpty(output.path)) !== normalize(output.content)) stale.push(output.label)
  }
  if (stale.length > 0) {
    console.error('stale generated client artifact(s): ' + stale.join(', '))
    console.error('run: node scripts/build-client.mjs')
    process.exit(1)
  }
  console.log(
    'client artifacts are up to date (' +
      fragments.length +
      ' fragments, ' +
      Buffer.byteLength(normalize(source), 'utf8') +
      ' bytes, ' +
      entries.length +
      ' locale keys)',
  )
} else {
  mkdirSync(localeDir, { recursive: true })
  for (const output of outputs) writeFileSync(output.path, output.content, 'utf8')
  console.log(
    'wrote ' +
      outputs.length +
      ' artifacts from ' +
      fragments.length +
      ' fragments (' +
      Buffer.byteLength(normalize(source), 'utf8') +
      ' bytes, ' +
      entries.length +
      ' locale keys)',
  )
}
