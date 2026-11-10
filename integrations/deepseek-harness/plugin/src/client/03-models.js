/**
 * dsh-codebase-intelligence — 03-models
 *
 * Framework-free derivations from host route payloads / engine payloads to the
 * bounded rows and fact objects each view renders. Everything here is pure so
 * the headless tests can assert it without a browser or a React runtime.
 */

    /* ------------------------------------------------------------------ */
    /* Shared fact blocks                                                 */
    /* ------------------------------------------------------------------ */

    /** `budgets` block of one engine payload. */
    function budgetFacts(payload) {
      const budgets = isObject(payload) && isObject(payload.budgets) ? payload.budgets : {}
      return {
        maxTokens: toNumber(budgets.maxTokens, null),
        tokensEstimated: toNumber(budgets.tokensEstimated, null),
        tokenEstimator: typeof budgets.tokenEstimator === "string" ? budgets.tokenEstimator : "",
      }
    }

    function truncatedOf(payload) {
      return isObject(payload) && payload.truncated === true
    }

    function indexFacts(payload) {
      const index = isObject(payload) && isObject(payload.index) ? payload.index : {}
      return {
        schemaVersion: typeof index.schemaVersion === "string" ? index.schemaVersion : "",
        engineVersion: typeof index.engineVersion === "string" ? index.engineVersion : "",
        policyFingerprint: typeof index.policyFingerprint === "string" ? index.policyFingerprint : "",
        fingerprint: typeof index.fingerprint === "string" ? index.fingerprint : "",
      }
    }

    /** `repo` stats block; every number degrades to 0. */
    function repoStats(payload) {
      const repo = isObject(payload) && isObject(payload.repo) ? payload.repo : {}
      return {
        files: toNumber(repo.files, 0),
        symbols: toNumber(repo.symbols, 0),
        relations: toNumber(repo.relations, 0),
        languages: safeArray(repo.languages).length,
        topDirectories: safeArray(repo.topDirectories).length,
      }
    }

    function languageRows(payload) {
      const repo = isObject(payload) && isObject(payload.repo) ? payload.repo : {}
      return safeArray(repo.languages).map(function (row, index) {
        return {
          key: (typeof row.language === "string" ? row.language : "lang") + "-" + index,
          language: toText(row.language),
          files: toNumber(row.files, 0),
          symbols: toNumber(row.symbols, 0),
        }
      })
    }

    function directoryRows(payload) {
      const repo = isObject(payload) && isObject(payload.repo) ? payload.repo : {}
      return safeArray(repo.topDirectories).map(function (row, index) {
        return {
          key: (typeof row.path === "string" ? row.path : "dir") + "-" + index,
          path: toText(row.path) || ".",
          files: toNumber(row.files, 0),
          symbols: toNumber(row.symbols, 0),
        }
      })
    }

    function entryPointRows(source) {
      const points = isObject(source) && Array.isArray(source.entryPoints) ? source.entryPoints : safeArray(source)
      return points.map(function (row, index) {
        return {
          key: toText(row.path) + ":" + toNumber(row.line, 1) + ":" + index,
          path: toText(row.path),
          line: toNumber(row.line, 1),
          kind: toText(row.kind),
          symbol: toText(row.symbol),
        }
      })
    }

    /** Parse-issue summary: `{count, rows}` with a bounded sample. */
    function parseIssuesOf(payload) {
      const issues = isObject(payload) && isObject(payload.parseIssues) ? payload.parseIssues : {}
      const sample = safeArray(issues.sample).map(function (row, index) {
        return {
          key: toText(row.path) + ":" + index,
          path: toText(row.path),
          message: toText(row.message),
        }
      })
      return { count: toNumber(issues.count, sample.length), rows: sample }
    }

    /* ------------------------------------------------------------------ */
    /* /api/state                                                         */
    /* ------------------------------------------------------------------ */

    function stateFacts(state) {
      const facts = isObject(state) ? state : {}
      const index = isObject(facts.index) ? facts.index : {}
      const exports = isObject(facts.exports) ? facts.exports : {}
      const engine = isObject(facts.engine) ? facts.engine : {}
      const git = isObject(facts.git) ? facts.git : {}
      const root = typeof facts.root === "string" ? facts.root : ""
      return {
        root: root,
        workspace: basenameOf(root),
        fingerprint: typeof index.fingerprint === "string" ? shortHash(index.fingerprint) : "",
        engineVersion: typeof index.engineVersion === "string" ? index.engineVersion : "",
        engineAvailable: engine.available === true,
        pythonVersion: typeof engine.pythonVersion === "string" ? engine.pythonVersion : "",
        outDir: typeof exports.outDir === "string" && exports.outDir.length > 0 ? exports.outDir : DEFAULT_EXPORT_DIR,
        exportsStale: exports.stale === true,
        exportsFiles: safeArray(exports.files).length,
        exportsError: typeof exports.error === "string" ? exports.error : "",
        gitBranch: typeof git.branch === "string" ? git.branch : "",
        gitDirty: git.dirty === true,
        repo: isObject(facts.repo) ? facts.repo : null,
        entryPoints: safeArray(facts.entryPoints),
      }
    }

    /* ------------------------------------------------------------------ */
    /* /api/overview                                                      */
    /* ------------------------------------------------------------------ */

    function overviewFacts(payload, state) {
      const facts = stateFacts(state)
      const stats = repoStats(payload)
      const index = indexFacts(payload)
      const issues = parseIssuesOf(payload)
      return {
        stats: stats,
        budget: budgetFacts(payload),
        truncated: truncatedOf(payload),
        index: index,
        issues: issues,
        workspace: facts.workspace,
        fingerprint: index.fingerprint ? shortHash(index.fingerprint) : facts.fingerprint,
        engineVersion: index.engineVersion || facts.engineVersion,
        exports: {
          outDir: facts.outDir,
          stale: facts.exportsStale,
          files: facts.exportsFiles,
          error: facts.exportsError,
        },
      }
    }

    /* ------------------------------------------------------------------ */
    /* /api/map                                                           */
    /* ------------------------------------------------------------------ */

    function mapEntryRows(payload) {
      return safeArray(isObject(payload) ? payload.entries : []).map(function (entry, index) {
        const symbols = safeArray(entry.symbols)
        const symbolText = symbols
          .slice(0, 8)
          .map(function (symbol) {
            const name = toText(symbol.name)
            const line = toNumber(symbol.line, null)
            return line === null ? name : name + ":" + line
          })
          .join(" · ")
        return {
          key: toText(entry.path) + "-" + index,
          path: toText(entry.path),
          language: toText(entry.language),
          symbolCount: symbols.length,
          symbolsText: symbols.length === 0 ? "" : clampText(symbolText + (symbols.length > 8 ? " …" : ""), 160),
        }
      })
    }

    function mapOmitted(payload) {
      const omitted = isObject(payload) && isObject(payload.omitted) ? payload.omitted : {}
      return { files: toNumber(omitted.files, 0), symbols: toNumber(omitted.symbols, 0) }
    }

    /* ------------------------------------------------------------------ */
    /* /api/search                                                        */
    /* ------------------------------------------------------------------ */

    function searchResultRows(payload) {
      return safeArray(isObject(payload) ? payload.results : []).map(function (hit, index) {
        const path = toText(hit.path)
        const line = toNumber(hit.line, null)
        return {
          key: path + ":" + (line === null ? "" : line) + ":" + index,
          path: path,
          line: line,
          symbol: toText(hit.symbol),
          kind: toText(hit.kind),
          language: toText(hit.language),
          score: toNumber(hit.score, null),
          match: toText(hit.match),
        }
      })
    }

    /* ------------------------------------------------------------------ */
    /* /api/dependencies (+ /api/impact)                                  */
    /* ------------------------------------------------------------------ */

    function dependencyNodeRows(payload) {
      return safeArray(isObject(payload) ? payload.nodes : []).map(function (node, index) {
        const id = toText(node.id)
        return {
          key: id || "node-" + index,
          id: id,
          path: toText(node.path),
          symbol: toText(node.symbol),
          distance: toNumber(node.distance, null),
        }
      })
    }

    function dependencyEdgeRows(payload) {
      return safeArray(isObject(payload) ? payload.edges : []).map(function (edge, index) {
        const from = toText(edge.from)
        const to = toText(edge.to)
        return {
          key: from + "->" + to + ":" + index,
          from: from,
          to: to,
          type: toText(edge.type),
          status: toText(edge.status),
          evidence: toText(edge.evidence),
        }
      })
    }

    function dependencyStatusTone(status) {
      switch (toText(status)) {
        case "resolved":
          return "ok"
        case "unresolved":
        case "ambiguous":
          return "warn"
        case "external":
          return "muted"
        default:
          return "muted"
      }
    }

    function dependencyTargetText(payload) {
      if (!isObject(payload) || !isObject(payload.target)) return ""
      const target = payload.target
      if (typeof target.path === "string" && target.path.length > 0) return target.path
      if (typeof target.symbol === "string" && target.symbol.length > 0) return target.symbol
      return ""
    }

    function impactFacts(payload) {
      const changed = isObject(payload) && isObject(payload.changed) ? payload.changed : {}
      return {
        changedFiles: safeArray(changed.files).map(toText),
        changedSymbols: safeArray(changed.symbols).map(toText),
        affectedFiles: safeArray(isObject(payload) ? payload.affectedFiles : []).map(function (row, index) {
          return {
            key: toText(row.path) + "-" + index,
            path: toText(row.path),
            distance: toNumber(row.distance, null),
            confidence: toText(row.confidence),
            reason: toText(row.reason),
          }
        }),
        affectedSymbols: safeArray(isObject(payload) ? payload.affectedSymbols : []).map(function (row, index) {
          return {
            key: (toText(row.id) || toText(row.symbol)) + "-" + index,
            id: toText(row.id),
            path: toText(row.path),
            symbol: toText(row.symbol),
            distance: toNumber(row.distance, null),
            confidence: toText(row.confidence),
          }
        }),
        truncated: truncatedOf(payload),
      }
    }

    /** Parse a comma-separated repository path list (bounded, de-duplicated). */
    function splitCommaList(value, limit) {
      const text = toText(value)
      if (!text) return []
      const max = Math.max(1, Math.floor(toNumber(limit, MAX_IMPACT_FILES)))
      const seen = Object.create(null)
      const out = []
      const parts = text.split(",")
      for (let index = 0; index < parts.length; index += 1) {
        const item = parts[index].trim()
        if (!item || seen[item]) continue
        seen[item] = true
        out.push(item)
        if (out.length >= max) break
      }
      return out
    }

    /* ------------------------------------------------------------------ */
    /* /api/context                                                       */
    /* ------------------------------------------------------------------ */

    function contextItemRows(payload) {
      return safeArray(isObject(payload) ? payload.items : []).map(function (item, index) {
        return {
          key: toText(item.path) + ":" + toNumber(item.startLine, 0) + "-" + index,
          path: toText(item.path),
          startLine: toNumber(item.startLine, null),
          endLine: toNumber(item.endLine, null),
          symbol: toText(item.symbol),
          kind: toText(item.kind),
          tokensEstimated: toNumber(item.tokensEstimated, null),
          reason: toText(item.reason),
          excerpt: toText(item.excerpt),
        }
      })
    }

    function contextOmittedRows(payload) {
      const omitted = isObject(payload) ? payload.omitted : []
      if (Array.isArray(omitted)) {
        return omitted.map(function (row, index) {
          return {
            key: toText(row.path) + ":" + index,
            path: toText(row.path),
            reason: toText(row.reason),
            count: toNumber(row.count, null),
          }
        })
      }
      return []
    }

    /* ------------------------------------------------------------------ */
    /* Export plan                                                        */
    /* ------------------------------------------------------------------ */

    function normalizeExportStatus(status) {
      const value = toText(status)
      return EXPORT_STATUSES.indexOf(value) >= 0 ? value : "missing"
    }

    function exportStatusTone(status) {
      switch (normalizeExportStatus(status)) {
        case "created":
          return "ok"
        case "updated":
          return "warn"
        case "unchanged":
          return "muted"
        default:
          return "danger"
      }
    }

    function exportStatusLabelKey(status) {
      return "export." + normalizeExportStatus(status)
    }

    /**
     * Map the preview/write `files` list onto the fixed seven-file checklist,
     * matching by basename (paths may carry the outDir prefix).
     */
    function exportRowsFor(files) {
      const byName = Object.create(null)
      const list = safeArray(files)
      for (let index = 0; index < list.length; index += 1) {
        const item = list[index]
        if (!isObject(item)) continue
        const name = basenameOf(item.path)
        if (name) byName[name] = item
      }
      return EXPORT_FILES.map(function (name) {
        const hit = byName[name] || null
        return {
          key: name,
          name: name,
          path: hit ? toText(hit.path) : "",
          status: hit ? normalizeExportStatus(hit.status) : "missing",
          bytes: hit ? toNumber(hit.bytes, null) : null,
        }
      })
    }

    function exportCounts(rows) {
      const counts = { created: 0, updated: 0, unchanged: 0, missing: 0, total: 0 }
      const list = safeArray(rows)
      for (let index = 0; index < list.length; index += 1) {
        const status = normalizeExportStatus(list[index] && list[index].status)
        counts[status] += 1
        counts.total += 1
      }
      return counts
    }

    /** Git facts with safe defaults; `command` is the host's or the fixed fallback. */
    function gitFactsOf(git) {
      const value = isObject(git) ? git : {}
      return {
        available: value.available === true,
        branch: typeof value.branch === "string" ? value.branch : "",
        dirty: value.dirty === true,
        exportChanges: safeArray(value.exportChanges).map(toText),
        command: gitCommandOf(value),
      }
    }

    /* ------------------------------------------------------------------ */
    /* Session selection for the full-page fallback                       */
    /* ------------------------------------------------------------------ */

    /**
     * Selector over a SessionListState snapshot: the most recently updated
     * session id, used only by the root-scope fallback panel (the sidebar pane
     * receives `sessionId` directly). Returns "" for an empty/absent list.
     */
    function selectRecentSession(snapshot) {
      if (!isObject(snapshot)) return ""
      const ids = safeArray(snapshot.ids)
      const byId = isObject(snapshot.byId) ? snapshot.byId : {}
      let best = ""
      let bestAt = -1
      for (let index = 0; index < ids.length; index += 1) {
        const id = toText(ids[index])
        if (!id) continue
        const row = byId[id]
        const updatedAt = row && typeof row.updatedAt === "number" && Number.isFinite(row.updatedAt) ? row.updatedAt : 0
        if (updatedAt >= bestAt) {
          bestAt = updatedAt
          best = id
        }
      }
      return best
    }

    function viewById(id) {
      const value = toText(id)
      for (let index = 0; index < VIEWS.length; index += 1) {
        if (VIEWS[index].id === value) return VIEWS[index]
      }
      return VIEWS[0]
    }
