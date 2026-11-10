/**
 * Headless unit suite for the dsh-codebase-intelligence client half.
 *
 * `client.js` is evaluated in a `node:vm` sandbox with a `__ModuleLoader__`
 * capture stub, a tiny React stub and a localStorage stub — no browser, no
 * network, no real DSH. The assertions cover the loader contract, activation
 * with and without the right-sidebar services, the zh/en dictionary parity,
 * the pure payload/URL/CSS helpers and the built artifact freshness.
 */

import { spawnSync } from 'node:child_process'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import nodeAssert from 'node:assert/strict'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'

/**
 * `deepEqual` that compares serialized values: objects produced inside the vm
 * sandbox have their own realm's prototypes, so strict prototype checks would
 * reject otherwise identical data.
 */
const assert = Object.assign({}, nodeAssert, {
  deepEqual(actual, expected, message) {
    nodeAssert.deepEqual(JSON.parse(JSON.stringify(actual)), JSON.parse(JSON.stringify(expected)), message)
  },
})

const pluginRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const clientPath = join(pluginRoot, 'client.js')
const localeDir = join(pluginRoot, 'locale')
const clientSource = readFileSync(clientPath, 'utf8')
const packageJson = JSON.parse(readFileSync(join(pluginRoot, 'package.json'), 'utf8'))

/* ---------------------------------------------------------------------- */
/* Sandbox harness                                                        */
/* ---------------------------------------------------------------------- */

function createStorage(initial) {
  const store = new Map(Object.entries(initial || {}))
  return {
    getItem(key) {
      return store.has(key) ? store.get(key) : null
    },
    setItem(key, value) {
      store.set(key, String(value))
    },
    removeItem(key) {
      store.delete(key)
    },
    __store: store,
  }
}

function createReactStub() {
  return {
    createElement(type, props) {
      const children = Array.prototype.slice.call(arguments, 2)
      return { type, props: Object.assign({}, props || {}, children.length > 0 ? { children } : {}) }
    },
    Component: class Component {
      constructor(props) {
        this.props = props || {}
      }
      setState() {}
    },
    useState(initial) {
      const value = typeof initial === 'function' ? initial() : initial
      return [value, function () {}]
    },
    useEffect() {},
    useRef(value) {
      return { current: value }
    },
    useCallback(fn) {
      return fn
    },
    useMemo(fn) {
      return fn()
    },
  }
}

/**
 * Evaluate `client.js` the way the DSH module loader does and return the plugin
 * object plus its `__test__` surface.
 */
function loadClient(options = {}) {
  const registrations = []
  const storage = options.storage || createStorage()
  const windowStub = {
    localStorage: storage,
    navigator: { language: options.language || 'zh-CN' },
    __ModuleLoader__: {
      load(registration) {
        registrations.push(registration)
      },
    },
  }
  const reactStub = createReactStub()
  const sandbox = {
    window: windowStub,
    navigator: windowStub.navigator,
    console: { log() {}, warn() {}, error() {} },
    setTimeout,
    clearTimeout,
    queueMicrotask,
    Intl,
    AbortController,
    fetch: options.fetch || (() => Promise.reject(new Error('network disabled in the headless suite'))),
  }
  sandbox.globalThis = sandbox
  vm.createContext(sandbox)
  new vm.Script(clientSource, { filename: 'client.js' }).runInContext(sandbox)

  assert.equal(registrations.length, 1, 'the bundle must register exactly one module factory')
  const registration = registrations[0]
  const requested = []
  const plugin = registration.factory(function fakeRequire(name) {
    requested.push(name)
    if (name === 'react') return reactStub
    throw new Error(`unexpected module request: ${name}`)
  })
  assert.deepEqual(requested, ['react'], 'react is the only module a client bundle may require')
  return { registration, plugin, __test__: plugin.__test__, sandbox, storage, windowStub }
}

const loaded = loadClient()
const T = loaded.__test__

/** Minimal fake client context; `options` toggles the optional services. */
function createFakeHost(options = {}) {
  const ledger = {
    effects: [],
    locales: [],
    slotQueries: [],
    registrations: [],
    tabDefinitions: [],
    opens: [],
    deps: null,
    bound: null,
  }
  const locale = {
    register(namespace, dictionaries) {
      ledger.locales.push({ namespace, dictionaries })
      return function dispose() {}
    },
    bind(namespace) {
      ledger.bound = namespace
      return function boundT(key, vars) {
        let text = 'zh:' + key
        if (vars && typeof vars === 'object') {
          for (const name of Object.keys(vars)) text += ':' + name + '=' + String(vars[name])
        }
        return text
      }
    },
  }
  const slots = {
    inject(name, factory) {
      ledger.slotQueries.push(name)
      const dispose = factory()
      return typeof dispose === 'function' ? dispose : function () {}
    },
    register(definition, component) {
      ledger.registrations.push({ definition, component })
      return function () {}
    },
  }
  const ctx = {
    locale,
    slots,
    effect(fn, label) {
      ledger.effects.push(label)
      const dispose = fn()
      return typeof dispose === 'function' ? dispose : function () {}
    },
  }
  if (options.optionalServices === true) {
    ctx.inject = function inject(deps, callback) {
      ledger.deps = deps
      const scope = Object.assign({}, ctx, {
        sidebarRightTabs: {
          register(definition) {
            ledger.tabDefinitions.push(definition)
            return function () {}
          },
        },
        sidebarRight: {
          openTabIn(sessionId, kind) {
            ledger.opens.push([sessionId, kind])
          },
        },
      })
      return callback(scope)
    }
  } else if (options.injectAbsent !== true) {
    ctx.inject = function inject(deps) {
      ledger.deps = deps
      // Real Cordis never invokes the callback while the services are absent.
      return function () {}
    }
  }
  return { ctx, ledger }
}

function registrationOf(ledger, slotName) {
  return ledger.registrations.filter((entry) => entry.definition && entry.definition.name === slotName)[0] || null
}

/* ---------------------------------------------------------------------- */
/* Loader contract                                                        */
/* ---------------------------------------------------------------------- */

test('client.js registers the package module id through __ModuleLoader__', () => {
  assert.equal(loaded.registration.id, 'dsh-codebase-intelligence')
  assert.equal(loaded.registration.id, packageJson.name)
  assert.equal(typeof loaded.registration.factory, 'function')
  assert.ok(Object.prototype.hasOwnProperty.call(packageJson.dsh || {}, 'client'))
  assert.equal((packageJson.dsh.client || {}).platform, 'web')
})

test('the plugin object declares slots+locale and the pure test surface', () => {
  const plugin = loaded.plugin
  assert.deepEqual(plugin.inject, ['slots', 'locale'])
  assert.equal(plugin.name, 'dsh-codebase-intelligence')
  assert.equal(typeof plugin.apply, 'function')
  assert.equal(typeof plugin.__test__, 'object')
  for (const name of [
    'apiUrl',
    'apiGet',
    'apiPost',
    'requestHeaders',
    'makeT',
    'readLang',
    'writeLang',
    'exportRowsFor',
    'selectRecentSession',
    'boundedRows',
    'STYLES',
    'DICTIONARIES',
  ]) {
    assert.ok(T[name] !== undefined, `__test__.${name} must be exported`)
  }
  assert.equal(T.components.Panel, T.components.Panel, 'component identity is stable')
  for (const name of ['Panel', 'MainPanel', 'PanePanel', 'GuideEntryCard', 'PanelIcon', 'ViewRouter']) {
    assert.equal(typeof T.components[name], 'function', `components.${name} must be a component`)
  }
  assert.equal(typeof T.components.PanelBoundary, 'function')
})

test('VERSION matches the package manifest', () => {
  assert.equal(T.VERSION, packageJson.version)
  assert.equal(T.PKG_ID, packageJson.name)
})

/* ---------------------------------------------------------------------- */
/* Activation                                                             */
/* ---------------------------------------------------------------------- */

test('fallback panellist + main panel are always registered', () => {
  const host = createFakeHost({ injectAbsent: true })
  assert.doesNotThrow(() => T.apply(host.ctx))
  assert.deepEqual(host.ledger.locales.length, 1)
  assert.equal(host.ledger.locales[0].namespace, T.NS)
  assert.deepEqual(host.ledger.locales[0].dictionaries, T.DICTIONARIES)
  assert.deepEqual(host.ledger.slotQueries, ['sidebar.panellist', 'main'])

  const panellist = registrationOf(host.ledger, 'sidebar.panellist')
  assert.ok(panellist, 'sidebar.panellist must be registered')
  assert.equal(panellist.definition.id, T.NS)
  assert.equal(panellist.definition.order, 26)
  assert.equal(panellist.definition.locale, T.NS)
  assert.equal(typeof panellist.definition.label, 'function')
  // The locale-bound thunk is used, so the label follows the DSH locale.
  assert.equal(panellist.definition.label(), 'zh:panel.title')
  assert.equal(panellist.component, T.components.PanelIcon)

  const main = registrationOf(host.ledger, 'main')
  assert.ok(main, 'main must be registered')
  assert.deepEqual(main.definition, { name: 'main', key: T.NS, locale: T.NS })
  assert.equal(main.component, T.components.MainPanel)
})

test('right-sidebar services add the tab type, pane body and guide entry', () => {
  const host = createFakeHost({ optionalServices: true })
  assert.doesNotThrow(() => T.apply(host.ctx))
  assert.deepEqual(host.ledger.deps, ['sidebarRightTabs', 'sidebarRight'])
  assert.equal(host.ledger.tabDefinitions.length, 1)
  const definition = host.ledger.tabDefinitions[0]
  assert.equal(definition.id, T.NS)
  assert.equal(definition.kind, T.NS)
  assert.equal(definition.multiple, false)
  assert.equal(typeof definition.title, 'function')
  assert.equal(definition.title(), 'zh:panel.title')
  assert.equal(Array.isArray(definition.guide), true)
  assert.equal(definition.guide.length, 1)
  assert.equal(definition.guide[0].id, 'open')
  assert.equal(typeof definition.guide[0].title, 'function')
  assert.equal(typeof definition.guide[0].description, 'function')

  // Fallback registrations still happen alongside the right-sidebar seats.
  assert.ok(registrationOf(host.ledger, 'sidebar.panellist'))
  assert.ok(registrationOf(host.ledger, 'main'))
  assert.ok(host.ledger.slotQueries.includes('sidebar.right.pane.tab'))
  assert.ok(host.ledger.slotQueries.includes('sidebar.right.tab.guide.entry'))

  const pane = registrationOf(host.ledger, 'sidebar.right.pane.tab')
  assert.ok(pane, 'the pane body must be registered')
  assert.equal(pane.definition.key, T.NS)
  assert.equal(pane.definition.locale, T.NS)
  assert.equal(pane.component, T.components.PanePanel)

  const guide = registrationOf(host.ledger, 'sidebar.right.tab.guide.entry')
  assert.ok(guide, 'the Start-guide entry must be registered')
  assert.equal(guide.definition.key, T.NS)
  assert.equal(guide.component, T.components.GuideEntryCard)
  assert.equal(typeof guide.definition.inject, 'function')
  const injected = guide.definition.inject('session-1')
  injected.open()
  assert.deepEqual(host.ledger.opens, [['session-1', T.NS]])
  guide.definition.inject('').open()
  assert.deepEqual(host.ledger.opens, [['session-1', T.NS]], 'a missing session must not open anything')
})

test('the guide entry follows the native Start-row structure', () => {
  const element = T.components.GuideEntryCard({
    t: T.makeT('zh'),
    title: '代码库情报',
    description: '浏览仓库结构',
    open: () => {},
  })
  assert.equal(element.type, 'button')
  assert.equal(element.props.className, 'cbi-guide-entry')
  const [icon, text] = element.props.children
  assert.equal(icon.props.className, 'cbi-guide-icon')
  assert.equal(text.props.className, 'cbi-guide-text')
  assert.deepEqual(text.props.children.map((child) => child.props.className), ['cbi-guide-title', 'cbi-guide-desc'])
  assert.deepEqual(text.props.children[0].props.children, ['代码库情报'])
  assert.deepEqual(text.props.children[1].props.children, ['浏览仓库结构'])
})

test('activation degrades to the fallback panel when the services are absent', () => {
  const host = createFakeHost()
  assert.doesNotThrow(() => T.apply(host.ctx))
  assert.deepEqual(host.ledger.deps, ['sidebarRightTabs', 'sidebarRight'])
  assert.equal(host.ledger.tabDefinitions.length, 0, 'no tab type without the services')
  assert.ok(registrationOf(host.ledger, 'sidebar.panellist'))
  assert.ok(registrationOf(host.ledger, 'main'))
})

test('activation never throws on empty, hostile or partial contexts', () => {
  assert.doesNotThrow(() => T.apply({}))
  assert.doesNotThrow(() => T.apply(null))
  assert.doesNotThrow(() => T.apply(undefined))
  assert.doesNotThrow(() =>
    T.apply({
      slots: {
        inject() {
          throw new Error('slots.inject failed')
        },
        register() {
          throw new Error('slots.register failed')
        },
      },
      locale: {
        register() {
          throw new Error('locale.register failed')
        },
        bind() {
          throw new Error('locale.bind failed')
        },
      },
      effect() {
        throw new Error('effect failed')
      },
      inject() {
        throw new Error('inject failed')
      },
    }),
  )
  assert.doesNotThrow(() => T.apply({ slots: {}, locale: {} }))
})

test('a duplicate tab registration is tolerated', () => {
  const host = createFakeHost({ optionalServices: true })
  const scopeInject = host.ctx.inject
  host.ctx.inject = function inject(deps, callback) {
    return scopeInject.call(host.ctx, deps, function (scope) {
      scope.sidebarRightTabs.register = function register() {
        throw new Error('id already in use')
      }
      return callback(scope)
    })
  }
  assert.doesNotThrow(() => T.apply(host.ctx))
  assert.ok(registrationOf(host.ledger, 'main'), 'the fallback panel survives a tab collision')
})

/* ---------------------------------------------------------------------- */
/* Dictionaries, views and export file set                                */
/* ---------------------------------------------------------------------- */

test('zh/en dictionaries have identical key sets and match TEXT_ENTRIES', () => {
  const zhKeys = Object.keys(T.DICTIONARIES.zh).sort()
  const enKeys = Object.keys(T.DICTIONARIES.en).sort()
  assert.deepEqual(zhKeys, enKeys)
  assert.equal(zhKeys.length, T.TEXT_ENTRIES.length)
  for (const row of T.TEXT_ENTRIES) {
    assert.equal(row.length, 3, `TEXT_ENTRIES row for ${row[0]} must be [key, zh, en]`)
    assert.equal(T.DICTIONARIES.zh[row[0]], row[1])
    assert.equal(T.DICTIONARIES.en[row[0]], row[2])
    assert.ok(row[1].length > 0 && row[2].length > 0)
  }
  for (const key of ['panel.title', 'view.overview', 'view.export', 'export.write', 'budget.bar']) {
    assert.ok(Object.prototype.hasOwnProperty.call(T.DICTIONARIES.zh, key), `missing dictionary key ${key}`)
  }
})

test('generated locale/*.json mirrors the embedded dictionaries', () => {
  for (const locale of ['zh', 'en']) {
    const parsed = JSON.parse(readFileSync(join(localeDir, `${locale}.json`), 'utf8'))
    assert.deepEqual(parsed, T.DICTIONARIES[locale])
  }
  const files = readdirSync(localeDir).filter((name) => name.endsWith('.json')).sort()
  assert.deepEqual(files, ['en.json', 'zh.json'])
})

test('export counters are total-driven instead of hardcoded', () => {
  for (const locale of ['zh', 'en']) {
    const dictionary = T.DICTIONARIES[locale]
    for (const key of ['export.fileCount', 'export.writeConfirm']) {
      assert.ok(dictionary[key].includes('{total}'), `${locale}:${key} must use {total}`)
      assert.ok(!/\b7\b/u.test(dictionary[key]), `${locale}:${key} still hardcodes the old file count`)
    }
  }
})

test('every t() key referenced by the fragments exists in the dictionaries', () => {
  const sourceDir = join(pluginRoot, 'src', 'client')
  const zh = T.DICTIONARIES.zh
  const missing = []
  for (const name of readdirSync(sourceDir).filter((file) => file.endsWith('.js'))) {
    const text = readFileSync(join(sourceDir, name), 'utf8')
    const pattern = /\bt\(\s*"([^"]+)"/gu
    let match
    while ((match = pattern.exec(text)) !== null) {
      if (!Object.prototype.hasOwnProperty.call(zh, match[1])) missing.push(`${name}: ${match[1]}`)
    }
    const labelPattern = /\blabelKey:\s*"([^"]+)"/gu
    while ((match = labelPattern.exec(text)) !== null) {
      if (!Object.prototype.hasOwnProperty.call(zh, match[1])) missing.push(`${name}: ${match[1]}`)
    }
  }
  assert.deepEqual(missing, [])
})

test('graph models normalize, filter, and lay out a focused slice', () => {
  const nodes = [
    { id: 'sym:a', label: 'main', kind: 'symbol', path: 'a.py', symbolKind: 'function', line: 3, side: 'focus' },
    { id: 'sym:b', label: 'helper', kind: 'symbol', path: 'a.py', symbolKind: 'function', line: 9, side: 'out' },
    { id: 'file:a.py', label: 'a.py', kind: 'file', path: 'a.py', side: 'in' },
    { id: 'unresolved:missing', label: 'missing', kind: 'unresolved', side: 'out' },
  ]
  const edges = [
    { from: 'sym:a', to: 'sym:b', type: 'calls', status: 'resolved', evidence: 'resolver', count: 2, sites: [{ path: 'a.py', startLine: 3 }] },
    { from: 'sym:a', to: 'unresolved:missing', type: 'references', status: 'unresolved', evidence: 'heuristic', count: 1 },
  ]
  const rows = T.graphNodeRows(nodes)
  const edgeRows = T.graphEdgeRows(edges)
  assert.equal(rows.length, 4)
  assert.equal(edgeRows.length, 2)
  assert.equal(edgeRows[0].count, 2)
  assert.equal(T.graphEdgeTone(edgeRows[0]), 'resolved')
  assert.equal(T.graphEdgeTone(edgeRows[1]), 'heuristic')
  assert.equal(T.graphVisibleEdges(edgeRows, { showUnresolved: true }).length, 2)
  assert.equal(T.graphVisibleEdges(edgeRows, { showUnresolved: false }).length, 1)
  assert.equal(T.graphNodeMatches(rows[1], 'HELPER'), true)
  assert.equal(T.graphNodeMatches(rows[2], 'a.py'), true)
  const matches = T.graphMatchMap(rows, 'helper')
  assert.ok(matches['sym:b'])
  assert.equal(matches['file:a.py'], undefined)
  const degrees = T.graphDegrees(rows, edgeRows)
  assert.equal(degrees['sym:a'].out, 2)
  assert.equal(degrees['sym:a'].in, 0)
  const layout = T.graphLayout(rows, edgeRows)
  assert.equal(layout.mode, 'focus')
  assert.ok(layout.positions['sym:a'])
  assert.ok(layout.positions['sym:b'].x > layout.positions['sym:a'].x)
  assert.ok(layout.positions['file:a.py'].x < layout.positions['sym:a'].x)
  assert.deepEqual(T.graphLayout(rows, edgeRows).positions, layout.positions)
  const geometry = T.graphEdgeGeometry(layout.positions['sym:a'], layout.positions['sym:b'])
  assert.ok(geometry.path.startsWith('M '))
  assert.ok(geometry.labelX > 0 && geometry.labelY > 0)
})

test('graph layout falls back to deterministic layers and a grid', () => {
  const nodes = [
    { id: 'dir:a', label: 'a', kind: 'dir' },
    { id: 'file:x', label: 'x', kind: 'file' },
    { id: 'file:y', label: 'y', kind: 'file' },
  ]
  const grid = T.graphLayout(nodes, [])
  assert.equal(grid.mode, 'grid')
  assert.ok(grid.positions['dir:a'])
  assert.ok(grid.width > 0 && grid.height > 0)
  const layered = T.graphLayout(nodes, [
    { from: 'file:x', to: 'file:y', type: 'imports', status: 'resolved', evidence: 'resolver', count: 1 },
  ])
  assert.equal(layered.mode, 'layered')
  assert.ok(layered.positions['file:x'].x < layered.positions['file:y'].x)
})

test('views and export files follow the contract order', () => {
  assert.deepEqual(
    T.VIEWS.map((view) => view.id),
    ['overview', 'map', 'graph', 'search', 'dependencies', 'context', 'export'],
  )
  for (const view of T.VIEWS) {
    assert.ok(Object.prototype.hasOwnProperty.call(T.DICTIONARIES.zh, view.labelKey), `missing ${view.labelKey}`)
    assert.ok(typeof view.glyph === 'string' && view.glyph.length > 0)
  }
  assert.deepEqual(T.EXPORT_FILES, [
    'overview.json',
    'repo-map.json',
    'graph.snapshot.json',
    'ARCHITECTURE.generated.md',
    'REPO_MAP.md',
    'dependencies.mmd',
    'CONTEXT_BRIEF.md',
    'manifest.json',
  ])
  assert.equal(T.EXPORT_FILES.length, 8)
  assert.equal(T.MAX_ROWS, 50)
  assert.equal(T.viewById('search').id, 'search')
  assert.equal(T.viewById('nope').id, 'overview')
})

/* ---------------------------------------------------------------------- */
/* HTTP builders                                                          */
/* ---------------------------------------------------------------------- */

test('API URL builders carry the prefix, session and encoded query', () => {
  assert.equal(
    T.apiUrl('/api/search', { session: 's 1', query: 'a/b' }),
    '/dsh-codebase-intelligence/api/search?session=s%201&query=a%2Fb',
  )
  assert.equal(T.apiUrl('/api/state', {}), '/dsh-codebase-intelligence/api/state')
  assert.equal(T.apiUrl('api/state', {}), '/dsh-codebase-intelligence/api/state')
  assert.equal(T.apiUrl('/api/map', { session: 'x', focus: undefined }), '/dsh-codebase-intelligence/api/map?session=x')
  assert.equal(T.encodeQuery({ session: 'x', empty: '' }), 'session=x')
  assert.equal(T.encodeQuery(null), '')
})

test('request headers and POST bodies follow the host contract', () => {
  assert.deepEqual(T.requestHeaders(), { 'x-dsh-codebase-intelligence': '1' })
  assert.deepEqual(T.requestHeaders({ 'content-type': 'application/json' }), {
    'x-dsh-codebase-intelligence': '1',
    'content-type': 'application/json',
  })
  assert.deepEqual(T.withSession('', { query: 'q' }), { query: 'q' })
  assert.deepEqual(T.withSession('s1', { query: 'q' }), { session: 's1', query: 'q' })
  assert.deepEqual(T.refreshBody('s1'), { session: 's1' })
  assert.deepEqual(T.refreshBody(''), {})
  assert.deepEqual(T.exportWriteBody('s1'), { session: 's1', confirm: true })
  assert.deepEqual(T.exportWriteBody(''), { confirm: true })
  assert.equal(T.gitCommandOf({ command: 'git add x && git commit -m y' }), 'git add x && git commit -m y')
  assert.equal(T.gitCommandOf(null), T.GIT_FALLBACK_COMMAND)
})

test('the response envelope unwraps {ok:true,data} and passes failures through', () => {
  assert.deepEqual(T.unwrapEnvelope({ ok: true, data: { a: 1 } }), { a: 1 })
  assert.deepEqual(T.unwrapEnvelope({ ok: true }), {})
  assert.deepEqual(T.unwrapEnvelope({ ok: false, code: 'x', message: 'y' }), { ok: false, code: 'x', message: 'y' })
  assert.deepEqual(T.unwrapEnvelope(null), {})
  const failure = new Error('boom')
  failure.code = 'failed'
  assert.equal(T.messageOf(failure), 'boom')
  assert.equal(T.errorCodeOf(failure), 'failed')
})

/* ---------------------------------------------------------------------- */
/* Language persistence                                                   */
/* ---------------------------------------------------------------------- */

test('language defaults to Chinese and persists an explicit EN choice', () => {
  assert.equal(T.detectLang(), 'zh', 'Chinese must be the default')
  assert.equal(T.makeT('zh')('panel.title'), '代码库情报')
  assert.equal(T.makeT('en')('panel.title'), 'Codebase Intelligence')
  assert.equal(T.makeT('zh')('common.moreRows', { n: 3 }), '另有 3 条未显示')
  assert.equal(T.makeT('en')('common.moreRows', { n: 3 }), '3 more rows not shown')

  const store = createStorage()
  const fresh = loadClient({ storage: store })
  assert.equal(fresh.__test__.readLang(), '')
  fresh.__test__.writeLang('en')
  assert.equal(store.getItem('dsh-codebase-intelligence.lang'), 'en')
  assert.equal(fresh.__test__.readLang(), 'en')
  assert.equal(fresh.__test__.detectLang(), 'en')
  fresh.__test__.writeLang('fr')
  assert.equal(fresh.__test__.readLang(), 'en', 'invalid languages are ignored')

  const preset = loadClient({ storage: createStorage({ 'dsh-codebase-intelligence.lang': 'zh' }) })
  assert.equal(preset.__test__.detectLang(), 'zh')
})

/* ---------------------------------------------------------------------- */
/* Styling contract                                                       */
/* ---------------------------------------------------------------------- */

test('the stylesheet is namespaced and built from DSH theme tokens', () => {
  const css = T.STYLES
  assert.ok(css.includes('var(--dsw-'), 'theme tokens must be used')
  assert.ok(css.includes('.cbi-root'), 'the root class must exist')
  assert.ok(css.includes('.cbi-tabs'))
  assert.ok(css.includes('.cbi-table'))
  assert.ok(css.includes('.cbi-badge'))
  assert.ok(!css.includes(':root'), 'no global variable overrides')
  assert.ok(!/(^|\})\s*(html|body)\s*\{/u.test(css), 'no global element selectors')
  // Every concrete class in the sheet is namespaced with cbi-.
  const classes = css.match(/\.([a-zA-Z][a-zA-Z0-9_-]*)/gu) || []
  const offending = classes.filter((name) => !name.startsWith('.cbi-'))
  assert.deepEqual(offending, [])
  assert.ok(/--cbi-[a-z0-9-]+:\s*var\(--dsw-/u.test(css), 'component variables chain to DSH tokens')
})

/* ---------------------------------------------------------------------- */
/* Pure payload models                                                    */
/* ---------------------------------------------------------------------- */

const OVERVIEW_FIXTURE = {
  ok: true,
  truncated: true,
  budgets: { maxTokens: 900, tokensEstimated: 677, tokenEstimator: 'chars4-wide-v1' },
  index: { schemaVersion: '1', engineVersion: '0.1.0', policyFingerprint: 'p'.repeat(64), fingerprint: 'f'.repeat(64) },
  repo: {
    files: 147,
    symbols: 2188,
    relations: 3530,
    languages: [
      { language: 'python', files: 81, symbols: 1417 },
      { language: 'javascript', files: 23, symbols: 753 },
    ],
    topDirectories: [{ path: 'src', files: 35, symbols: 937 }],
  },
  entryPoints: [{ path: 'src/app.py', line: 12, kind: 'function', symbol: 'src.app.main' }],
  parseIssues: { count: 1, sample: [{ path: 'broken.py', message: 'syntax error' }] },
}

test('overview/languages/directories/entry points derive bounded rows', () => {
  assert.deepEqual(T.repoStats(OVERVIEW_FIXTURE), {
    files: 147,
    symbols: 2188,
    relations: 3530,
    languages: 2,
    topDirectories: 1,
  })
  assert.deepEqual(T.budgetFacts(OVERVIEW_FIXTURE), {
    maxTokens: 900,
    tokensEstimated: 677,
    tokenEstimator: 'chars4-wide-v1',
  })
  assert.equal(T.truncatedOf(OVERVIEW_FIXTURE), true)
  assert.equal(T.indexFacts(OVERVIEW_FIXTURE).engineVersion, '0.1.0')

  const languages = T.languageRows(OVERVIEW_FIXTURE)
  assert.equal(languages.length, 2)
  assert.equal(languages[0].language, 'python')
  assert.equal(languages[0].files, 81)

  const directories = T.directoryRows(OVERVIEW_FIXTURE)
  assert.equal(directories[0].path, 'src')
  assert.equal(directories[0].symbols, 937)

  const entries = T.entryPointRows(OVERVIEW_FIXTURE)
  assert.equal(entries.length, 1)
  assert.equal(entries[0].line, 12)
  assert.equal(entries[0].path, 'src/app.py')

  const issues = T.parseIssuesOf(OVERVIEW_FIXTURE)
  assert.equal(issues.count, 1)
  assert.equal(issues.rows[0].message, 'syntax error')
  assert.deepEqual(T.parseIssuesOf(null), { count: 0, rows: [] })

  const facts = T.overviewFacts(OVERVIEW_FIXTURE, null)
  assert.equal(facts.truncated, true)
  assert.equal(facts.stats.files, 147)
  assert.equal(facts.fingerprint.length, 12)
})

test('state facts expose workspace, engine and export status safely', () => {
  const facts = T.stateFacts({
    root: 'F:\\QuestionForAI\\codebase-intelligence',
    index: { fingerprint: 'a'.repeat(64), engineVersion: '0.1.0' },
    exports: { outDir: 'docs/codebase-intelligence', stale: true, files: [{ path: 'x' }] },
    engine: { available: true, pythonVersion: '3.11.9' },
    git: { branch: 'main', dirty: false },
  })
  assert.equal(facts.workspace, 'codebase-intelligence')
  assert.equal(facts.fingerprint.length, 12)
  assert.equal(facts.engineAvailable, true)
  assert.equal(facts.pythonVersion, '3.11.9')
  assert.equal(facts.outDir, 'docs/codebase-intelligence')
  assert.equal(facts.exportsStale, true)
  assert.equal(facts.exportsFiles, 1)
  assert.equal(facts.gitBranch, 'main')
  const empty = T.stateFacts(null)
  assert.equal(empty.workspace, '')
  assert.equal(empty.engineAvailable, false)
  assert.equal(empty.outDir, 'docs/codebase-intelligence')
})

test('map/search/dependency/context payload rows are derived defensively', () => {
  const mapRows = T.mapEntryRows({
    entries: [{ path: 'src/a.py', language: 'python', symbols: [{ name: 'main', line: 3 }, { name: 'x', line: 9 }] }],
    omitted: { files: 15, symbols: 687 },
  })
  assert.equal(mapRows.length, 1)
  assert.equal(mapRows[0].symbolCount, 2)
  assert.ok(mapRows[0].symbolsText.includes('main:3'))
  assert.deepEqual(T.mapOmitted({ omitted: { files: 15, symbols: 687 } }), { files: 15, symbols: 687 })

  const searchRows = T.searchResultRows({
    results: [{ path: 'src/a.py', line: 4, symbol: 'main', kind: 'function', language: 'python', score: 2.4997, match: 'def main' }],
  })
  assert.equal(searchRows[0].path, 'src/a.py')
  assert.equal(searchRows[0].score, 2.4997)

  const nodes = T.dependencyNodeRows({ nodes: [{ id: 'file:src/a.py', path: 'src/a.py', distance: 0 }] })
  assert.equal(nodes[0].id, 'file:src/a.py')
  const edges = T.dependencyEdgeRows({ edges: [{ from: 'a', to: 'b', type: 'imports', status: 'resolved', evidence: 'resolver' }] })
  assert.equal(edges[0].status, 'resolved')
  assert.equal(T.dependencyStatusTone('resolved'), 'ok')
  assert.equal(T.dependencyStatusTone('unresolved'), 'warn')
  assert.equal(T.dependencyTargetText({ target: { path: 'src/a.py' } }), 'src/a.py')
  assert.equal(T.dependencyTargetText({ target: { symbol: 'sym:main' } }), 'sym:main')
  assert.equal(T.dependencyTargetText(null), '')

  const items = T.contextItemRows({
    items: [{ path: 'src/a.py', startLine: 10, endLine: 20, symbol: 'main', kind: 'function', tokensEstimated: 56, reason: 'lexical', excerpt: 'def main():\n    pass' }],
  })
  assert.equal(items[0].startLine, 10)
  assert.equal(items[0].endLine, 20)
  assert.equal(items[0].tokensEstimated, 56)
  assert.equal(T.contextOmittedRows({ omitted: [{ path: 'src/b.py', reason: 'budget' }] })[0].reason, 'budget')
  assert.deepEqual(T.contextOmittedRows(null), [])

  const impact = T.impactFacts({
    changed: { files: ['src/a.py'], symbols: [] },
    affectedFiles: [{ path: 'src/b.py', distance: 1, confidence: 'high', reason: 'imports' }],
    affectedSymbols: [{ id: 'sym:x', path: 'src/b.py', symbol: 'x', distance: 1, confidence: 'medium' }],
  })
  assert.deepEqual(impact.changedFiles, ['src/a.py'])
  assert.equal(impact.affectedFiles.length, 1)
  assert.equal(impact.affectedSymbols[0].symbol, 'x')
  assert.deepEqual(T.splitCommaList(' a.py, b.py ,, a.py ', 50), ['a.py', 'b.py'])
  assert.deepEqual(T.splitCommaList('', 50), [])
})

test('export checklist maps the fixed eight files onto preview statuses', () => {
  const rows = T.exportRowsFor([
    { path: 'docs/codebase-intelligence/overview.json', status: 'created', bytes: 1024 },
    { path: 'docs/codebase-intelligence/repo-map.json', status: 'unchanged', bytes: 20 },
    { path: 'docs/codebase-intelligence/ARCHITECTURE.generated.md', status: 'updated', bytes: 2048 },
    { path: 'docs/codebase-intelligence/manifest.json', status: 'unchanged', bytes: 512 },
  ])
  assert.equal(rows.length, T.EXPORT_FILES.length)
  assert.deepEqual(
    rows.map((row) => row.name),
    T.EXPORT_FILES,
  )
  const byName = Object.fromEntries(rows.map((row) => [row.name, row]))
  assert.equal(byName['overview.json'].status, 'created')
  assert.equal(byName['repo-map.json'].status, 'unchanged')
  assert.equal(byName['ARCHITECTURE.generated.md'].status, 'updated')
  assert.equal(byName['REPO_MAP.md'].status, 'missing')
  assert.equal(byName['overview.json'].bytes, 1024)
  const counts = T.exportCounts(rows)
  assert.deepEqual(counts, { created: 1, updated: 1, unchanged: 2, missing: 4, total: 8 })
  assert.equal(T.exportStatusTone('created'), 'ok')
  assert.equal(T.exportStatusTone('updated'), 'warn')
  assert.equal(T.exportStatusTone('unchanged'), 'muted')
  assert.equal(T.exportStatusTone('missing'), 'danger')
  assert.equal(T.exportStatusLabelKey('created'), 'export.created')
  assert.equal(T.normalizeExportStatus('bogus'), 'missing')
})

test('git facts and bounded helpers are deterministic', () => {
  const git = T.gitFactsOf({ available: true, branch: 'main', dirty: true, exportChanges: [' M docs/x'], command: 'git add docs' })
  assert.equal(git.branch, 'main')
  assert.equal(git.dirty, true)
  assert.deepEqual(git.exportChanges, [' M docs/x'])
  assert.equal(git.command, 'git add docs')
  const emptyGit = T.gitFactsOf(null)
  assert.equal(emptyGit.available, false)
  assert.equal(emptyGit.command, T.GIT_FALLBACK_COMMAND)

  const bounded = T.boundedRows(Array.from({ length: 60 }, (_, index) => index))
  assert.equal(bounded.rows.length, 50)
  assert.equal(bounded.total, 60)
  assert.equal(bounded.omitted, 10)
  assert.equal(T.boundedRows([]).omitted, 0)

  assert.equal(T.basenameOf('F:\\QuestionForAI\\codebase-intelligence'), 'codebase-intelligence')
  assert.equal(T.basenameOf('docs/codebase-intelligence/overview.json'), 'overview.json')
  assert.equal(T.basenameOf(''), '')
  assert.equal(T.shortHash('a'.repeat(64)).length, 12)
  assert.equal(T.shortHash('abc'), 'abc')
  assert.equal(T.pathLineOf({ path: 'src/a.py', line: 3 }), 'src/a.py:3')
  assert.equal(T.pathLineOf({ path: 'src/a.py', startLine: 7 }), 'src/a.py:7')
  assert.equal(T.pathLineOf(null), '')
  const excerpt = T.boundedExcerpt(Array.from({ length: 30 }, (_, index) => 'line ' + index).join('\n'), 18, 2400)
  assert.ok(excerpt.endsWith('…'))
  assert.equal(excerpt.split('\n').length, 19)
  assert.equal(T.clampText('abcdef', 4), 'abc…')
  assert.equal(T.fmtBytes(2048), '2.0 KB')
  assert.equal(T.fmtInt(1234567), '1,234,567')

  assert.equal(
    T.selectRecentSession({ ids: ['a', 'b'], byId: { a: { updatedAt: 1 }, b: { updatedAt: 5 } } }),
    'b',
  )
  assert.equal(T.selectRecentSession({ ids: [], byId: {} }), '')
  assert.equal(T.selectRecentSession(null), '')
})

/* ---------------------------------------------------------------------- */
/* Artifact freshness and size                                            */
/* ---------------------------------------------------------------------- */

test('the shipped bundle stays under the 224 KiB contract cap', () => {
  const bytes = Buffer.byteLength(clientSource, 'utf8')
  assert.ok(bytes <= T.MAX_BUNDLE_BYTES, `client.js is ${bytes} bytes (> ${T.MAX_BUNDLE_BYTES})`)
  assert.ok(clientSource.includes('window.__ModuleLoader__.load({'))
  // A classic script: strip comments, then assert there is no ESM syntax.
  const stripped = clientSource.replace(/\/\*[\s\S]*?\*\//gu, '').replace(/^\s*\/\/.*$/gmu, '')
  assert.ok(!/^\s*(?:import|export)\s/mu.test(stripped), 'the shipped client must be a dependency-free classic script')
})

test('scripts/build-client.mjs --check reports the artifacts as fresh', () => {
  const result = spawnSync(process.execPath, ['scripts/build-client.mjs', '--check'], {
    cwd: pluginRoot,
    encoding: 'utf8',
  })
  assert.equal(result.status, 0, result.stderr || result.stdout)
  assert.match(result.stdout, /up to date/u)
})
