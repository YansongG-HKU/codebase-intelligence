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
    /* Graph explorer                                                     */
    /* ------------------------------------------------------------------ */

    const GRAPH_NODE_WIDTH = 184
    const GRAPH_NODE_HEIGHT = 54
    const GRAPH_COLUMN_GAP = 54
    const GRAPH_ROW_GAP = 26
    const GRAPH_PADDING = 28
    const GRAPH_KIND_ORDER = { dir: 0, file: 1, symbol: 2, unresolved: 3 }

    function graphNodeRows(nodes) {
      const rows = []
      const seen = Object.create(null)
      safeArray(nodes).forEach(function (node, index) {
        if (!isObject(node)) return
        const id = toText(node.id)
        if (!id || seen[id]) return
        seen[id] = true
        const kind = GRAPH_KIND_ORDER[toText(node.kind)] === undefined ? "file" : toText(node.kind)
        rows.push({
          key: id,
          id: id,
          label: toText(node.label) || id,
          kind: kind,
          path: toText(node.path),
          symbolKind: toText(node.symbolKind),
          line: toNumber(node.line, 0),
          side: ["focus", "in", "out", "both"].indexOf(toText(node.side)) >= 0 ? toText(node.side) : "",
          index: index,
        })
      })
      return rows
    }

    function graphEdgeRows(edges) {
      return safeArray(edges).map(function (edge, index) {
        const sites = []
        const seenSites = Object.create(null)
        safeArray(isObject(edge) ? edge.sites : []).some(function (span) {
          const path = toText(span && span.path)
          const startLine = toNumber(span && span.startLine, 1)
          const key = path + ":" + startLine
          if (!path || seenSites[key]) return false
          seenSites[key] = true
          sites.push({
            path: path,
            startLine: startLine,
            startColumn: toNumber(span && span.startColumn, 0),
            endLine: toNumber(span && span.endLine, null),
            endColumn: toNumber(span && span.endColumn, null),
          })
          return sites.length >= 3
        })
        return {
          key: toText(edge && edge.from) + "\u0000" + toText(edge && edge.to) + "\u0000" + index,
          from: toText(edge && edge.from),
          to: toText(edge && edge.to),
          type: toText(edge && edge.type),
          status: toText(edge && edge.status) || "unresolved",
          evidence: toText(edge && edge.evidence) || "heuristic",
          count: Math.max(1, toNumber(edge && edge.count, 1)),
          sites: sites,
        }
      })
    }

    function graphNodeTone(node) {
      const kind = toText(node && node.kind)
      return GRAPH_KIND_ORDER[kind] === undefined ? "file" : kind
    }

    function graphEdgeTone(edge) {
      const status = toText(edge && edge.status)
      const evidence = toText(edge && edge.evidence)
      if (status === "resolved" && evidence !== "heuristic") return "resolved"
      if (evidence === "heuristic") return "heuristic"
      return "unresolved"
    }

    function graphVisibleEdges(edges, options) {
      const value = isObject(options) ? options : {}
      const relation = toText(value.relation)
      const showUnresolved = value.showUnresolved !== false
      const query = toText(value.query).toLowerCase()
      const matches = value.matches
      return safeArray(edges).filter(function (edge) {
        if (!isObject(edge) || !toText(edge.from) || !toText(edge.to)) return false
        if (!showUnresolved && graphEdgeTone(edge) !== "resolved") return false
        if (relation && toText(edge.type) !== relation) return false
        if (query && matches && (!matches[toText(edge.from)] && !matches[toText(edge.to)])) return false
        return true
      })
    }

    function graphDegrees(nodes, edges) {
      const degrees = Object.create(null)
      safeArray(nodes).forEach(function (node) {
        if (node && toText(node.id)) degrees[toText(node.id)] = { in: 0, out: 0, total: 0 }
      })
      safeArray(edges).forEach(function (edge) {
        if (!isObject(edge)) return
        const from = degrees[toText(edge.from)]
        const to = degrees[toText(edge.to)]
        if (from) { from.out += 1; from.total += 1 }
        if (to) { to.in += 1; to.total += 1 }
      })
      return degrees
    }

    function graphNodeMatches(node, query) {
      const value = toText(query).trim().toLowerCase()
      if (!value) return true
      const haystack = [
        toText(node && node.label),
        toText(node && node.path),
        toText(node && node.kind),
        toText(node && node.symbolKind),
      ].join("\n").toLowerCase()
      return haystack.indexOf(value) >= 0
    }

    function graphMatchMap(nodes, query) {
      const matches = Object.create(null)
      safeArray(nodes).forEach(function (node) {
        if (node && toText(node.id) && graphNodeMatches(node, query)) matches[toText(node.id)] = true
      })
      return matches
    }

    /** Deterministic, bounded layout: focus gets in/out columns; otherwise DAG
     * columns when the slice has a small number of layers, else a kind-ordered
     * grid. Returns absolute positions for node cards plus the canvas size. */
    function graphLayout(nodes, edges) {
      const list = graphNodeRows(nodes)
      const edgeList = graphEdgeRows(edges).filter(function (edge) {
        return edge.from !== edge.to
      })
      const positions = Object.create(null)
      const byId = Object.create(null)
      list.forEach(function (node) { byId[node.id] = node })
      const focus = list.filter(function (node) { return node.side === "focus" })[0]
      let width = 0
      let height = 0
      let mode = "grid"
      if (focus) {
        mode = "focus"
        const incoming = []
        const outgoing = []
        list.forEach(function (node) {
          if (node.id === focus.id) return
          if (node.side === "in") incoming.push(node)
          else if (node.side === "out" || node.side === "both") outgoing.push(node)
          else outgoing.push(node)
        })
        const columns = [incoming, [focus], outgoing]
        const rows = Math.max(1, incoming.length, outgoing.length)
        const columnWidth = GRAPH_NODE_WIDTH + GRAPH_COLUMN_GAP
        width = GRAPH_PADDING * 2 + (columns.length - 1) * columnWidth + GRAPH_NODE_WIDTH
        height = GRAPH_PADDING * 2 + rows * GRAPH_NODE_HEIGHT + Math.max(0, rows - 1) * GRAPH_ROW_GAP
        columns.forEach(function (column, columnIndex) {
          column.forEach(function (node, rowIndex) {
            const centered = columnIndex === 1 && column.length === 1
            positions[node.id] = {
              x: GRAPH_PADDING + columnIndex * columnWidth,
              y: centered ? Math.round((height - GRAPH_NODE_HEIGHT) / 2) : GRAPH_PADDING + rowIndex * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP),
            }
          })
        })
      } else if (edgeList.length > 0) {
        const indegree = Object.create(null)
        const adjacency = Object.create(null)
        list.forEach(function (node) { indegree[node.id] = 0; adjacency[node.id] = [] })
        edgeList.forEach(function (edge) {
          if (!byId[edge.from] || !byId[edge.to] || edge.from === edge.to) return
          indegree[edge.to] += 1
          adjacency[edge.from].push(edge.to)
        })
        const sortKey = function (id) {
          const node = byId[id]
          return (GRAPH_KIND_ORDER[node.kind] * 100000) + node.label.toLowerCase() + "\u0000" + id
        }
        const ready = list.filter(function (node) { return indegree[node.id] === 0 }).map(function (node) { return node.id }).sort(function (a, b) { return sortKey(a) < sortKey(b) ? -1 : sortKey(a) > sortKey(b) ? 1 : 0 })
        const level = Object.create(null)
        list.forEach(function (node) { level[node.id] = -1 })
        ready.forEach(function (id) { level[id] = 0 })
        const queue = ready.slice()
        while (queue.length > 0) {
          const id = queue.shift()
          adjacency[id].forEach(function (target) {
            level[target] = Math.max(level[target], level[id] + 1)
            indegree[target] -= 1
            if (indegree[target] === 0) queue.push(target)
          })
        }
        let maxLevel = -1
        list.forEach(function (node) { if (level[node.id] >= 0) maxLevel = Math.max(maxLevel, level[node.id]) })
        list.forEach(function (node) { if (level[node.id] < 0) level[node.id] = maxLevel + 1 })
        const layers = []
        list.forEach(function (node) {
          const index = level[node.id]
          if (!layers[index]) layers[index] = []
          layers[index].push(node)
        })
        const sorted = layers.filter(Boolean).map(function (layer) {
          return layer.slice().sort(function (a, b) { return sortKey(a.id) < sortKey(b.id) ? -1 : sortKey(a.id) > sortKey(b.id) ? 1 : 0 })
        })
        const rowMax = sorted.reduce(function (best, layer) { return Math.max(best, layer.length) }, 0)
        if (sorted.length > 0 && sorted.length <= 6 && rowMax <= 16) {
          mode = "layered"
          const columnWidth = GRAPH_NODE_WIDTH + GRAPH_COLUMN_GAP
          width = GRAPH_PADDING * 2 + (sorted.length - 1) * columnWidth + GRAPH_NODE_WIDTH
          height = GRAPH_PADDING * 2 + rowMax * GRAPH_NODE_HEIGHT + Math.max(0, rowMax - 1) * GRAPH_ROW_GAP
          sorted.forEach(function (layer, columnIndex) {
            const offset = Math.round((rowMax - layer.length) * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP) / 2)
            layer.forEach(function (node, rowIndex) {
              positions[node.id] = {
                x: GRAPH_PADDING + columnIndex * columnWidth,
                y: GRAPH_PADDING + offset + rowIndex * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP),
              }
            })
          })
        }
      }
      if (mode === "grid") {
        const columns = list.length > 12 ? 3 : list.length > 4 ? 2 : 1
        const sorted = list.slice().sort(function (a, b) {
          const order = GRAPH_KIND_ORDER[a.kind] - GRAPH_KIND_ORDER[b.kind]
          if (order !== 0) return order
          if (a.label.toLowerCase() < b.label.toLowerCase()) return -1
          if (a.label.toLowerCase() > b.label.toLowerCase()) return 1
          return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
        })
        const rows = Math.ceil(sorted.length / columns)
        const columnWidth = GRAPH_NODE_WIDTH + GRAPH_COLUMN_GAP
        width = GRAPH_PADDING * 2 + (columns - 1) * columnWidth + GRAPH_NODE_WIDTH
        height = GRAPH_PADDING * 2 + Math.max(1, rows) * GRAPH_NODE_HEIGHT + Math.max(0, rows - 1) * GRAPH_ROW_GAP
        sorted.forEach(function (node, index) {
          positions[node.id] = {
            x: GRAPH_PADDING + (index % columns) * columnWidth,
            y: GRAPH_PADDING + Math.floor(index / columns) * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP),
          }
        })
      }
      return {
        mode: mode,
        nodes: list,
        positions: positions,
        width: Math.max(width, GRAPH_NODE_WIDTH + GRAPH_PADDING * 2),
        height: Math.max(height, GRAPH_NODE_HEIGHT + GRAPH_PADDING * 2),
      }
    }

    /** Cubic edge route between two node cards; returns the path and its midpoint. */
    function graphEdgeGeometry(from, to) {
      const same = from && to && from.x === to.x && from.y === to.y
      if (same) {
        const x = from.x + GRAPH_NODE_WIDTH
        const y = from.y + 18
        return {
          path: "M " + x + " " + y + " C " + (x + 54) + " " + (y - 34) + " " + (x + 54) + " " + (y + 34) + " " + x + " " + (y + 18),
          labelX: x + 40,
          labelY: y,
        }
      }
      const forward = to.x >= from.x
      const sx = forward ? from.x + GRAPH_NODE_WIDTH : from.x
      const tx = forward ? to.x : to.x + GRAPH_NODE_WIDTH
      const sy = from.y + GRAPH_NODE_HEIGHT / 2
      const ty = to.y + GRAPH_NODE_HEIGHT / 2
      const bend = Math.max(36, Math.abs(tx - sx) * 0.45)
      const c1 = forward ? sx + bend : sx - bend
      const c2 = forward ? tx - bend : tx + bend
      return {
        path: "M " + sx + " " + sy + " C " + c1 + " " + sy + " " + c2 + " " + ty + " " + tx + " " + ty,
        labelX: (sx + tx) / 2,
        labelY: (sy + ty) / 2,
      }
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
     * Map the preview/write `files` list onto the fixed eight-file checklist,
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
