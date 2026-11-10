/**
 * dsh-codebase-intelligence — Host plugin entry.
 *
 * A decorator, following the proven DSH pattern: it injects the `agents`
 * service, waits for `agent/created` (and decorates Agents that were already
 * live when the plugin loaded), then registers the six `codebase_*` tools and
 * one short system-prompt section *inside that Agent's scope*. Nothing is
 * registered globally and there is no client UI.
 *
 * Failure policy: activation never throws. A bad row config degrades to
 * defaults; an Agent without a tool registry is skipped; a tool handler always
 * returns the shared error envelope instead of failing the model step.
 *
 * @module dsh-codebase-intelligence
 */

import { messageOf } from './lib/util.js'
import { resolveConfig } from './lib/config.js'
import { registerPanel } from './lib/panel.js'
import { createService } from './lib/service.js'
import { createTools } from './lib/tools.js'
import { promptSectionDefinition } from './lib/prompt.js'

/** The Harness service this plugin decorates. */
export const inject = ['agents']

/** Package name (also the bundle loader row id). */
export const name = 'dsh-codebase-intelligence'

/**
 * Plugin activation.
 *
 * @param {object} ctx the plugin's Cordis context (`agents` is injected)
 * @param {unknown} config the loader row config
 * @returns {() => void} disposer
 */
export function apply(ctx, config) {
  const log = {
    info: (message) => write(ctx, 'info', message),
    warn: (message) => write(ctx, 'warn', message),
  }

  let cfg
  try {
    cfg = resolveConfig(config)
  } catch (error) {
    log.warn(`could not resolve config; using defaults: ${messageOf(error)}`)
    try {
      cfg = resolveConfig({})
    } catch {
      log.warn('could not build default config; plugin inactive')
      return () => {}
    }
  }
  for (const message of Array.isArray(cfg.errors) ? cfg.errors : []) log.warn(`config: ${message}`)

  let service
  try {
    service = createService({ cfg, log })
  } catch (error) {
    log.warn(`could not create the engine service; plugin inactive: ${messageOf(error)}`)
    return () => {}
  }

  /** Agent bindings: agent id → disposer. */
  const bindings = new Map()
  /** Set when the optional web panel registered; null on headless profiles. */
  let panelDispose = null

  const decorate = (agent) => {
    try {
      if (!agent || typeof agent.id !== 'string' || agent.id.length === 0) return
      if (!agent.session || bindings.has(agent.id)) return
      // The panel resolves its repository root by session id; record it even if
      // this Agent has no tool registry (e.g. a read-only panel-only session).
      try {
        service.registerSession(agent)
      } catch {
        /* session bookkeeping must never block decoration */
      }
      if (!agent.ctx?.tools || typeof agent.ctx.tools.register !== 'function') {
        log.warn(`agent ${agent.id} has no tool registry; not decorating`)
        return
      }
      const disposers = []
      let toolCount = 0
      try {
        const definitions = createTools({ agent, cfg, service, log })
        toolCount = definitions.length
        for (const definition of definitions) {
          const dispose = agent.ctx.tools.register(definition)
          if (typeof dispose === 'function') disposers.push(dispose)
        }
        if (cfg.promptSection !== false && typeof agent.ctx.systemPrompt?.section === 'function') {
          const dispose = agent.ctx.systemPrompt.section(promptSectionDefinition())
          if (typeof dispose === 'function') disposers.push(dispose)
        }
      } catch (error) {
        for (const dispose of disposers.splice(0)) safeDispose(dispose)
        log.warn(`could not decorate agent ${agent.id}: ${messageOf(error)}`)
        return
      }
      bindings.set(agent.id, {
        dispose() {
          for (const dispose of disposers.splice(0)) safeDispose(dispose)
        },
      })
      log.info(`decorated ${agent.id}: ${toolCount} tool(s), promptSection=${cfg.promptSection !== false}`)
    } catch (error) {
      log.warn(`decoration failed for ${agent?.id ?? 'unknown agent'}: ${messageOf(error)}`)
    }
  }

  try {
    ctx.on('agent/created', (payload) => decorate(payload?.agent ?? payload))
    ctx.on('agent/disposed', (payload) => {
      const agent = payload?.agent ?? payload
      const binding = bindings.get(agent?.id)
      if (!binding) return
      binding.dispose()
      bindings.delete(agent.id)
    })
  } catch (error) {
    log.warn(`could not subscribe to agent lifecycle events: ${messageOf(error)}`)
  }

  try {
    for (const agent of ctx.agents?.list?.() ?? []) decorate(agent)
  } catch (error) {
    log.warn(`could not enumerate live agents: ${messageOf(error)}`)
  }

  // Optional web panel (right-sidebar tab + full-page fallback). Feature-gated:
  // a headless profile has no webServer and simply skips this block.
  if (cfg.panelEnabled !== false) {
    try {
      panelDispose = registerPanel({
        ctx,
        service,
        log,
        onExported: (data) => {
          try {
            if (typeof ctx.emit === 'function') {
              ctx.emit('codebase-intelligence/exported', {
                outDir: data?.outDir ?? null,
                files: Array.isArray(data?.files) ? data.files.length : 0,
                manifestFingerprint: data?.manifestFingerprint ?? null,
              })
            }
          } catch {
            /* optional interop event */
          }
        },
      })
    } catch (error) {
      log.warn(`could not register the panel: ${messageOf(error)}`)
    }
  }

  // Optional interop surface for other Host plugins: they may inject
  // `codebaseIntelligence` and call these read-only/export helpers without
  // importing our internals. Absent listeners are fine.
  try {
    const provide = ctx?.reflect?.provide
    if (typeof provide === 'function') {
      provide.call(ctx.reflect, 'codebaseIntelligence', {
        version: '0.1.0',
        resolveRoot: (sessionId) => service.resolveSessionRoot(sessionId),
        overview: (sessionId) => service.panelCall('overview', { maxTokens: 900 }, { sessionId }),
        exportPreview: (sessionId) => service.exportPreview({ sessionId }),
        exportWrite: (sessionId) => service.exportWrite({ sessionId }),
      })
    }
  } catch (error) {
    log.warn(`could not provide the codebaseIntelligence service: ${messageOf(error)}`)
  }

  log.info('active: six read-only codebase tools + static prompt section per agent')

  return () => {
    try {
      if (typeof panelDispose === 'function') panelDispose()
    } catch {
      /* panel disposal is best effort */
    }
    panelDispose = null
    for (const binding of bindings.values()) binding.dispose()
    bindings.clear()
    try {
      service.invalidate?.()
    } catch {
      /* disposal is best effort */
    }
  }
}

function write(ctx, level, message) {
  try {
    const logger = ctx?.logger
    if (typeof logger?.[level] === 'function') logger[level](`[dsh-codebase-intelligence] ${message}`)
  } catch {
    /* logging must never break plugin wiring */
  }
}

function safeDispose(dispose) {
  try {
    if (typeof dispose === 'function') dispose()
  } catch {
    /* an already-disposed registration is fine */
  }
}
