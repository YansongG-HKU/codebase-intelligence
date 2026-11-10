import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { estimateTokens, sha256Hex } from '../../lib/util.js'
import { PROMPT_TEXT } from '../../lib/prompt.js'

const SCRIPT = fileURLToPath(new URL('../../scripts/footprint.mjs', import.meta.url))
const PLUGIN_DIR = fileURLToPath(new URL('../../', import.meta.url))

/** Run scripts/footprint.mjs with this Node and parse its single JSON object. */
function measure() {
  const stdout = execFileSync(process.execPath, [SCRIPT], { cwd: PLUGIN_DIR, encoding: 'utf8', timeout: 60_000 })
  return { stdout, footprint: JSON.parse(stdout) }
}

test('footprint script prints exactly one JSON object with the documented fields', () => {
  const { footprint } = measure()
  assert.deepEqual(Object.keys(footprint).sort(), [
    'promptSectionBytes',
    'promptSectionTextHash',
    'promptSectionTokensEstimated',
    'toolCount',
    'toolSchemaBytes',
    'toolSchemaTokensEstimated',
  ])
  assert.equal(footprint.toolCount, 6)
  assert.equal(footprint.promptSectionTextHash, sha256Hex(PROMPT_TEXT))
  assert.equal(footprint.promptSectionBytes, Buffer.byteLength(PROMPT_TEXT, 'utf8'))
  assert.equal(footprint.promptSectionTokensEstimated, estimateTokens(PROMPT_TEXT))
})

test('the total model-facing tool schema stays within the 2200-token budget', () => {
  const { footprint } = measure()
  assert.ok(
    footprint.toolSchemaTokensEstimated <= 2_200,
    `tool schema estimates ${footprint.toolSchemaTokensEstimated} tokens (limit 2200)`,
  )
  assert.ok(footprint.toolSchemaBytes > 1_000, 'the schema must actually describe all six tools')
})

test('footprint output is deterministic', () => {
  const first = measure()
  const second = measure()
  assert.equal(first.stdout, second.stdout)
})
