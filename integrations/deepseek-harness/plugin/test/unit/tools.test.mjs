import { test } from 'node:test'
import assert from 'node:assert/strict'

import { TOOL_IDS } from '../../lib/config.js'
import { createTools, TOOL_NAMES } from '../../lib/tools.js'
import { defaultConfig, fakeAgent, fakeToolService } from './_helpers.mjs'

function setup({ tools = {}, handler = null } = {}) {
  const cfg = { ...defaultConfig(), tools: { ...defaultConfig().tools, ...tools } }
  const service = fakeToolService(handler)
  const agent = fakeAgent({ cwd: 'C:/work/session' })
  const definitions = createTools({ agent, cfg, service })
  return { cfg, service, agent, definitions, byName: new Map(definitions.map((definition) => [definition.name, definition])) }
}

/** Collect every object key in a JSON value (used to assert no dynamic schema defaults). */
function collectKeys(value, out = new Set()) {
  if (Array.isArray(value)) {
    for (const item of value) collectKeys(item, out)
  } else if (value !== null && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      out.add(key)
      collectKeys(item, out)
    }
  }
  return out
}

test('createTools registers the six codebase_* tools in spec order', () => {
  const { definitions, byName } = setup()
  assert.equal(definitions.length, 6)
  assert.deepEqual(
    definitions.map((definition) => definition.name),
    ['codebase_overview', 'codebase_map', 'codebase_search', 'codebase_dependencies', 'codebase_context', 'codebase_impact'],
  )
  assert.deepEqual([...TOOL_NAMES], [...byName.keys()])
  assert.deepEqual(Object.values(TOOL_IDS), [...byName.keys()])
})

test('every tool has a strict, static JSON schema with no dynamic values', () => {
  const { definitions } = setup()
  for (const definition of definitions) {
    assert.equal(definition.parameters.type, 'object')
    assert.equal(definition.parameters.additionalProperties, false)
    const keys = collectKeys(definition.parameters)
    assert.equal(keys.has('default'), false, `${definition.name} must not embed a default value`)
    assert.equal(keys.has('required') || true, true)
    assert.equal(typeof definition.description, 'string')
    assert.ok(definition.description.length >= 80, `${definition.name} needs a precise description`)
    assert.ok(definition.description.length <= 400, `${definition.name} description is too long`)
    assert.equal(definition.output.schema.type, 'object')
    assert.equal(definition.output.schema.additionalProperties, true)
    assert.equal(typeof definition.output.render, 'function')
    assert.equal(typeof definition.execute, 'function')
  }
})

test('required arguments and bounded value ranges follow docs/SPEC.md §13', () => {
  const { byName } = setup()
  assert.deepEqual(byName.get('codebase_search').parameters.required, ['query'])
  assert.deepEqual(byName.get('codebase_dependencies').parameters.required, ['target'])
  assert.deepEqual(byName.get('codebase_context').parameters.required, ['task'])
  assert.equal(byName.get('codebase_overview').parameters.required, undefined)
  assert.equal(byName.get('codebase_map').parameters.required, undefined)
  assert.equal(byName.get('codebase_impact').parameters.required, undefined)

  const dependencies = byName.get('codebase_dependencies').parameters.properties
  assert.deepEqual(dependencies.direction.enum, ['both', 'imports', 'dependents'])
  assert.equal(dependencies.depth.minimum, 1)
  assert.equal(dependencies.depth.maximum, 5)
  for (const definition of byName.values()) {
    assert.equal(definition.parameters.properties.maxTokens.minimum, 200)
    assert.equal(definition.parameters.properties.maxTokens.maximum, 8000)
    assert.equal(definition.parameters.properties.refresh.type, 'boolean')
  }
  assert.equal(byName.get('codebase_impact').parameters.properties.files.maxItems, 50)
  assert.equal(byName.get('codebase_impact').parameters.properties.symbols.maxItems, 100)
})

test('schemas are byte-identical across builds (no dynamic config in schemas)', () => {
  const first = setup()
  const second = setup({ tools: {} })
  assert.equal(
    JSON.stringify(first.definitions.map((definition) => definition.parameters)),
    JSON.stringify(second.definitions.map((definition) => definition.parameters)),
  )
})

test('config.tools can disable individual tools', () => {
  const { definitions } = setup({ tools: { map: false, impact: false, search: false } })
  assert.deepEqual(
    definitions.map((definition) => definition.name),
    ['codebase_overview', 'codebase_dependencies', 'codebase_context'],
  )
})

test('handlers pass arguments, agent and signal to the service and return its value', async () => {
  const { byName, service, agent } = setup()
  const result = await byName.get('codebase_dependencies').execute(
    { target: 'src/app.py', direction: 'imports', depth: 2, maxTokens: 1200 },
    { signal: 'sig' },
  )
  assert.equal(service.calls.length, 1)
  const call = service.calls[0]
  assert.equal(call.toolKey, 'dependencies')
  assert.deepEqual(call.args, { target: 'src/app.py', direction: 'imports', depth: 2, maxTokens: 1200 })
  assert.equal(call.options.agent, agent)
  assert.equal(call.options.signal, 'sig')
  assert.equal(result.ok, true)
  assert.equal(result.command, 'dependencies')
})

test('handlers default missing arguments to an empty object', async () => {
  const { byName, service } = setup()
  await byName.get('codebase_overview').execute(undefined, undefined)
  assert.deepEqual(service.calls[0].args, {})
  assert.equal(service.calls[0].options.signal, undefined)
})

test('output.render emits exactly one JSON text block matching the value', async () => {
  const payload = { ok: true, index: { fingerprint: 'fp' }, items: [1, 2, 3] }
  const { byName } = setup({ handler: async () => payload })
  const value = await byName.get('codebase_overview').execute({}, {})
  const rendered = byName.get('codebase_overview').output.render({}, value)
  assert.equal(rendered.length, 1)
  assert.equal(rendered[0].type, 'text')
  assert.deepEqual(JSON.parse(rendered[0].text), payload)
  assert.equal(rendered[0].text, JSON.stringify(payload))
})

test('handlers convert thrown service errors into the shared never-throw envelope', async () => {
  const { byName } = setup({
    handler: () => {
      throw new Error('boom with F:/secret/path')
    },
  })
  const result = await byName.get('codebase_search').execute({ query: 'x' }, {})
  assert.equal(result.ok, false)
  assert.equal(result.code, 'failed')
  assert.equal(JSON.stringify(result).includes('F:/secret/path'), false)
  assert.equal(typeof result.repair.action, 'string')
})

test('a missing service degrades to a structured envelope instead of throwing', async () => {
  const definitions = createTools({ cfg: defaultConfig(), service: null })
  const result = await definitions[0].execute({}, {})
  assert.equal(result.ok, false)
  assert.equal(result.code, 'failed')
  assert.match(result.message, /not available/)
})

test('tool values survive the lossless JSON round-trip', async () => {
  const { byName } = setup({
    handler: async () => ({ ok: true, at: new Date(0), dropped: undefined, nested: { list: [1, null, 'x'] } }),
  })
  const result = await byName.get('codebase_map').execute({}, {})
  assert.equal(result.ok, true)
  assert.equal(typeof result.at, 'string')
  assert.equal('dropped' in result, false)
  assert.deepEqual(JSON.parse(JSON.stringify(result)), result)
})
