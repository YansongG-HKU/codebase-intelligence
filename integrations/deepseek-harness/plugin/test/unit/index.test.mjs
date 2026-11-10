import { test } from 'node:test'
import assert from 'node:assert/strict'

import { apply, inject, name } from '../../index.js'
import { PROMPT_SECTION_NAME, PROMPT_SECTION_ORDER, PROMPT_TEXT } from '../../lib/prompt.js'
import { fakeAgent, fakeHost } from './_helpers.mjs'

test('module metadata matches the bundle package', () => {
  assert.deepEqual(inject, ['agents'])
  assert.equal(name, 'dsh-codebase-intelligence')
})

test('apply decorates live agents with six tools and one static prompt section', () => {
  const agent = fakeAgent({ cwd: 'C:/work/repo' })
  const host = fakeHost([agent])
  const dispose = apply(host.ctx, {})
  assert.equal(typeof dispose, 'function')

  assert.equal(agent.__test.registrations.length, 6)
  assert.equal(agent.__test.sections.length, 1)
  const section = agent.__test.sections[0]
  assert.equal(section.name, PROMPT_SECTION_NAME)
  assert.equal(section.order, PROMPT_SECTION_ORDER)
  assert.equal(section.interpolate, false)
  assert.equal(typeof section.text, 'function')
  assert.equal(section.text(), PROMPT_TEXT)
  assert.equal(section.text(), section.text(), 'prompt text must be static')

  dispose()
  assert.equal(agent.__test.registrations.length, 0)
  assert.equal(agent.__test.sections.length, 0)
})

test('agents created after activation are decorated and disposed correctly', () => {
  const first = fakeAgent({ id: 'agent-live', cwd: 'C:/work/one' })
  const host = fakeHost([first])
  const dispose = apply(host.ctx, {})

  const late = fakeAgent({ id: 'agent-late', cwd: 'C:/work/two' })
  host.emit('agent/created', { agent: late })
  assert.equal(late.__test.registrations.length, 6)
  assert.equal(late.__test.sections.length, 1)

  // A second creation event must not double-register.
  host.emit('agent/created', { agent: late })
  assert.equal(late.__test.registrations.length, 6)

  host.emit('agent/disposed', { agent: late })
  assert.equal(late.__test.registrations.length, 0)
  assert.equal(late.__test.sections.length, 0)

  dispose()
  assert.equal(first.__test.registrations.length, 0)
})

test('promptSection=false keeps the tools but registers no section', () => {
  const agent = fakeAgent()
  const host = fakeHost([agent])
  apply(host.ctx, { promptSection: false })
  assert.equal(agent.__test.registrations.length, 6)
  assert.equal(agent.__test.sections.length, 0)
})

test('tools toggles and per-tool budgets come from the loader row', () => {
  const agent = fakeAgent()
  const host = fakeHost([agent])
  apply(host.ctx, { tools: { map: false, impact: false } })
  const names = agent.__test.registrations.map((definition) => definition.name)
  assert.deepEqual(names, ['codebase_overview', 'codebase_search', 'codebase_dependencies', 'codebase_context'])
})

test('an agent without a tool registry is skipped without failing activation', () => {
  const agent = fakeAgent({ noTools: true })
  const host = fakeHost([agent])
  let dispose
  assert.doesNotThrow(() => {
    dispose = apply(host.ctx, {})
  })
  assert.equal(typeof dispose, 'function')
  assert.equal(agent.__test.sections.length, 0)
  dispose()
})

test('activation never throws on a hostile or empty context', () => {
  assert.doesNotThrow(() => {
    const dispose = apply({}, {})
    assert.equal(typeof dispose, 'function')
    dispose()
  })
  assert.doesNotThrow(() => {
    const hostile = {
      agents: {
        list() {
          throw new Error('list failed')
        },
      },
      logger: {
        info() {
          throw new Error('log failed')
        },
        warn() {
          throw new Error('log failed')
        },
      },
      on() {
        throw new Error('event bus failed')
      },
    }
    const dispose = apply(hostile, { maxTokens: 'nope', tools: 'also-nope' })
    assert.equal(typeof dispose, 'function')
    dispose()
  })
})

test('a malformed row config degrades to defaults', () => {
  const agent = fakeAgent()
  const host = fakeHost([agent])
  const dispose = apply(host.ctx, { maxTokens: { overview: 'huge' }, tools: [], promptSection: 'yes' })
  assert.equal(agent.__test.registrations.length, 6)
  assert.equal(agent.__test.sections.length, 1)
  dispose()
})


test('panel-only sessions are removed on agent disposal and plugin unload', () => {
  const first = fakeAgent({ id: 'first', noTools: true })
  const second = fakeAgent({ id: 'second', noTools: true })
  const host = fakeHost([first])
  let interop
  host.ctx.reflect = { provide(_name, service) { interop = service } }
  const dispose = apply(host.ctx, {})
  host.emit('agent/created', second)
  assert.ok(interop.resolveRoot('second'))
  host.emit('agent/disposed', second)
  assert.equal(interop.resolveRoot('second'), null)
  assert.equal(interop.resolveRoot(), interop.resolveRoot('first'))
  dispose()
  host.emit('agent/created', second)
  assert.equal(interop.resolveRoot(), null)
})
