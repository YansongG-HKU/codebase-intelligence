import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  PROMPT_SECTION_NAME,
  PROMPT_SECTION_ORDER,
  PROMPT_TEXT,
  promptSectionDefinition,
  promptSectionText,
} from '../../lib/prompt.js'
import { estimateTokens, sha256Hex, utf8Bytes } from '../../lib/util.js'

test('the prompt section is one static string of at most 120 words', () => {
  assert.equal(typeof PROMPT_TEXT, 'string')
  const words = PROMPT_TEXT.trim().split(/\s+/u)
  assert.ok(words.length > 40, 'the section must still describe the tools')
  assert.ok(words.length <= 120, `prompt section has ${words.length} words (limit 120)`)
  assert.equal(PROMPT_TEXT.includes('${'), false, 'no interpolation placeholders')
  assert.equal(PROMPT_TEXT.includes('{{'), false, 'no template placeholders')
  assert.equal(PROMPT_TEXT.includes('\n'), false, 'one paragraph, no line breaks')
})

test('the prompt section fits a small, measured token footprint', () => {
  const bytes = utf8Bytes(PROMPT_TEXT)
  const tokens = estimateTokens(PROMPT_TEXT)
  assert.ok(bytes < 1_200, `prompt section is ${bytes} bytes`)
  assert.ok(tokens < 300, `prompt section estimates ${tokens} tokens`)
  assert.equal(estimateTokens(''), 0)
  assert.equal(estimateTokens('abcd'), 1)
  assert.equal(estimateTokens('abcde'), 2)
  assert.equal(estimateTokens('中文'), 2)
  assert.equal(estimateTokens('中文ab'), 3)
})

test('promptSectionDefinition registers with interpolate:false and a getter', () => {
  const first = promptSectionDefinition()
  const second = promptSectionDefinition()
  assert.deepEqual(Object.keys(first).sort(), ['interpolate', 'name', 'order', 'text'])
  assert.equal(first.name, PROMPT_SECTION_NAME)
  assert.equal(first.order, PROMPT_SECTION_ORDER)
  assert.equal(first.interpolate, false)
  assert.equal(first.text(), PROMPT_TEXT)
  assert.equal(second.text(), first.text())
  assert.equal(promptSectionText(), PROMPT_TEXT)
})

test('the prompt text hash is stable', () => {
  assert.match(sha256Hex(PROMPT_TEXT), /^[0-9a-f]{64}$/)
  assert.equal(sha256Hex(promptSectionText()), sha256Hex(PROMPT_TEXT))
  assert.equal(PROMPT_SECTION_NAME, 'dsh-codebase-intelligence')
  assert.equal(PROMPT_SECTION_ORDER, 9110)
})
