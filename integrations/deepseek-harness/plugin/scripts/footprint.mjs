#!/usr/bin/env node
/**
 * Measure the model-facing token footprint of this plugin.
 *
 * This is the source of truth for docs/DSH_PLUGIN.md §"Token footprint" and
 * the regression guard in `test/unit/footprint.test.mjs`. It prints ONE JSON
 * object with exactly these fields:
 *
 *   toolCount                   number of registered tool definitions
 *   toolSchemaBytes             UTF-8 bytes of the model-facing schema
 *                               (names + descriptions + parameter schemas,
 *                               compact `JSON.stringify` form)
 *   toolSchemaTokensEstimated   chars4-wide-v1 estimate of the same text
 *   promptSectionBytes          UTF-8 bytes of the static prompt section
 *   promptSectionTokensEstimated chars4-wide-v1 estimate of the prompt text
 *   promptSectionTextHash       sha256 hex of the prompt text
 *
 * `chars4-wide-v1` is the estimate defined in docs/SPEC.md §4 and mirrored in
 * `lib/util.js`: ceil(ascii/4 + nonAscii), minimum 1 for non-empty input. It
 * is an estimate, not a tokenizer.
 *
 * Usage (bundled Node or any Node >= 22):
 *   node scripts/footprint.mjs
 */

import { resolveConfig } from '../lib/config.js'
import { promptSectionText } from '../lib/prompt.js'
import { createTools } from '../lib/tools.js'
import { estimateTokens, sha256Hex, utf8Bytes } from '../lib/util.js'

const cfg = resolveConfig({}, { env: {} })
const definitions = createTools({
  cfg,
  service: {
    async call() {
      return { ok: false, code: 'not_available', message: 'footprint measurement only' }
    },
  },
})

// The model-facing schema: exactly what the Harness shows the model, without
// the local `execute` closure or output projector.
const schemaText = JSON.stringify(
  definitions.map((definition) => ({
    name: definition.name,
    description: definition.description,
    parameters: definition.parameters,
  })),
)
const promptText = promptSectionText()

const footprint = {
  toolCount: definitions.length,
  toolSchemaBytes: utf8Bytes(schemaText),
  toolSchemaTokensEstimated: estimateTokens(schemaText),
  promptSectionBytes: utf8Bytes(promptText),
  promptSectionTokensEstimated: estimateTokens(promptText),
  promptSectionTextHash: sha256Hex(promptText),
}

process.stdout.write(`${JSON.stringify(footprint, null, 2)}\n`)
