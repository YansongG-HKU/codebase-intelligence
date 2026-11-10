/**
 * dsh-codebase-intelligence — 04-panel
 *
 * The one Panel component shared by the right-sidebar pane and the full-page
 * fallback: header facts, six views (概览/地图/搜索/依赖/上下文/生成), bounded
 * tables with path:line citations, budget/truncation markers, and the explicit
 * two-step export flow. Every request goes through the host routes in
 * PANEL_CONTRACT.md §3; the panel never runs git.
 */

    /* ------------------------------------------------------------------ */
    /* Small layout helpers                                               */
    /* ------------------------------------------------------------------ */

    function ViewLead(props) {
      const p = props || {}
      return h(
        "div",
        { className: "cbi-view-lead" },
        h("div", null, h("h2", null, p.title), p.subtitle ? h("p", null, p.subtitle) : null),
        p.actions ? h("div", { className: "cbi-section-actions" }, p.actions) : null,
      )
    }

    function Stats(props) {
      const p = props || {}
      const items = safeArray(p.items)
      if (items.length === 0) return null
      return h(
        "div",
        { className: "cbi-stats" },
        items.map(function (item, index) {
          return h(
            "div",
            { className: "cbi-stat", key: item.key || "stat-" + index },
            h("span", { className: "cbi-stat-label", title: item.title || undefined }, item.label),
            h("span", { className: "cbi-stat-value" }, item.value),
          )
        }),
      )
    }

    function Facts(props) {
      const p = props || {}
      const facts = safeArray(p.facts)
      if (facts.length === 0) return null
      return h(
        "div",
        { className: "cbi-facts" },
        facts.map(function (fact, index) {
          return h(
            "span",
            { className: "cbi-fact", key: fact.key || "fact-" + index },
            h("span", { className: "cbi-fact-key" }, fact.label),
            fact.value === undefined || fact.value === null
              ? null
              : h("span", { className: "cbi-fact-value", title: fact.raw || undefined }, displayValue(fact.value)),
          )
        }),
      )
    }

    /** Shared loading/error gate for the data views. */
    function loadGate(t, remote, errorTitle) {
      if (remote.status === "error") {
        return h(ErrorBox, { t: t, title: errorTitle, error: remote.error, onRetry: remote.reload })
      }
      if (remote.status === "loading" && !isObject(remote.data)) {
        return h(Loading, { t: t })
      }
      return null
    }

    function languageColumns(t) {
      return [
        { key: "language", label: t("common.language"), width: "34%" },
        { key: "files", label: t("overview.files"), className: "cbi-col-num", width: "33%", render: function (row) { return fmtInt(row.files) } },
        { key: "symbols", label: t("overview.symbols"), className: "cbi-col-num", width: "33%", render: function (row) { return fmtInt(row.symbols) } },
      ]
    }

    function directoryColumns(t) {
      return [
        { key: "path", label: t("overview.topDirectories"), render: function (row) { return h(PathRef, { path: row.path, static: true }) } },
        { key: "files", label: t("overview.files"), className: "cbi-col-num", width: "72px", render: function (row) { return fmtInt(row.files) } },
        { key: "symbols", label: t("overview.symbols"), className: "cbi-col-num", width: "72px", render: function (row) { return fmtInt(row.symbols) } },
      ]
    }

    /* ------------------------------------------------------------------ */
    /* 概览                                                               */
    /* ------------------------------------------------------------------ */

    function OverviewView(props) {
      const p = props || {}
      const t = p.t
      const remote = useLoad(
        function () {
          return apiGet("/api/overview", withSession(p.sessionId))
        },
        [p.sessionId, p.refreshToken],
      )
      const [rebuilding, setRebuilding] = useState(false)
      const [rebuildState, setRebuildState] = useState(null)
      const rebuild = function () {
        if (rebuilding) return
        setRebuilding(true)
        setRebuildState(null)
        apiPost("/api/refresh", refreshBody(p.sessionId), withSession(p.sessionId)).then(
          function () {
            setRebuilding(false)
            setRebuildState({ ok: true })
            remote.reload()
          },
          function (error) {
            setRebuilding(false)
            setRebuildState({ ok: false, message: messageOf(error) })
          },
        )
      }
      const gate = loadGate(t, remote, t("overview.loadError"))
      if (gate) return h("div", { className: "cbi-view" }, gate)
      const payload = isObject(remote.data) ? remote.data : {}
      const facts = overviewFacts(payload, p.state)
      const languages = languageRows(payload)
      const directories = directoryRows(payload)
      const entries = entryPointRows(payload)
      const issues = facts.issues.rows
      const exportFacts = facts.exports
      return h(
        "div",
        { className: "cbi-view" },
        h(BudgetBar, { t: t, budget: facts.budget, truncated: facts.truncated }),
        h(Stats, {
          items: [
            { key: "files", label: t("overview.files"), value: fmtInt(facts.stats.files) },
            { key: "symbols", label: t("overview.symbols"), value: fmtInt(facts.stats.symbols) },
            { key: "relations", label: t("overview.relations"), value: fmtInt(facts.stats.relations) },
            { key: "languages", label: t("overview.languages"), value: fmtInt(facts.stats.languages) },
          ],
        }),
        h(
          Section,
          { title: t("overview.languages"), count: languages.length > 0 ? fmtInt(languages.length) : null },
          languages.length > 0
            ? h(DataTable, { t: t, columns: languageColumns(t), rows: languages, emptyTitle: t("overview.noLanguages") })
            : h(EmptyState, { title: t("overview.noLanguages") }),
        ),
        h(
          Section,
          { title: t("overview.topDirectories"), count: directories.length > 0 ? fmtInt(directories.length) : null },
          directories.length > 0
            ? h(DataTable, { t: t, columns: directoryColumns(t), rows: directories, emptyTitle: t("overview.noDirectories") })
            : h(EmptyState, { title: t("overview.noDirectories") }),
        ),
        h(
          Section,
          { title: t("overview.entryPoints"), count: entries.length > 0 ? fmtInt(entries.length) : null },
          entries.length > 0
            ? h(DataTable, {
                t: t,
                rows: entries,
                columns: [
                  {
                    key: "path",
                    label: t("overview.entryPoints"),
                    render: function (row) {
                      return h(PathRef, { path: row.path, line: row.line, static: true })
                    },
                  },
                  { key: "kind", label: t("deps.type"), width: "70px" },
                ],
                emptyTitle: t("overview.noEntryPoints"),
              })
            : h(EmptyState, { title: t("overview.noEntryPoints") }),
        ),
        h(
          Section,
          {
            title: t("overview.parseIssues"),
            count: facts.issues.count > 0 ? t("overview.issuesCount", { n: fmtInt(facts.issues.count) }) : null,
          },
          issues.length > 0
            ? h(DataTable, {
                t: t,
                rows: issues,
                emptyTitle: t("overview.noIssues"),
                columns: [
                  { key: "path", label: t("common.path"), render: function (row) { return h(PathRef, { path: row.path, static: true }) } },
                  { key: "message", label: "—", render: function (row) { return h("span", { className: "cbi-muted" }, clampText(row.message, 120)) } },
                ],
              })
            : h(EmptyState, { title: t("overview.noIssues"), glyph: "check" }),
        ),
        h(
          Section,
          {
            title: t("overview.index"),
            actions: h(
              Btn,
              { size: "sm", glyph: "refresh", title: t("overview.rebuildHint"), disabled: rebuilding, onClick: rebuild },
              rebuilding ? t("overview.rebuilding") : t("overview.rebuild"),
            ),
          },
          h(Facts, {
            facts: [
              { key: "fingerprint", label: t("common.fingerprint"), value: shortHash(facts.index.fingerprint || facts.fingerprint), raw: facts.index.fingerprint },
              { key: "engine", label: t("overview.engine"), value: facts.engineVersion || "—" },
              { key: "policy", label: t("overview.policy"), value: shortHash(facts.index.policyFingerprint) },
              { key: "schema", label: "schema", value: facts.index.schemaVersion || "—" },
            ],
          }),
          h(
            "div",
            { className: "cbi-budget" },
            h("span", { className: "cbi-budget-label" }, t("overview.exports")),
            h("span", { className: "cbi-mono" }, exportFacts.outDir),
            exportFacts.stale
              ? h(Badge, { tone: "warn", title: exportFacts.error || undefined }, t("overview.exportStale"))
              : h(Badge, { tone: "ok" }, t("overview.exportFresh")),
            h("span", null, exportFacts.files > 0 ? t("overview.exportFiles", { n: fmtInt(exportFacts.files) }) : t("overview.exportMissing")),
            typeof p.onNavigate === "function"
              ? h(Btn, { size: "sm", glyph: "chevron", onClick: function () { p.onNavigate("export") } }, t("view.export"))
              : null,
          ),
          rebuildState
            ? h(
                "div",
                { className: "cbi-more" },
                rebuildState.ok ? t("overview.rebuildDone") : t("overview.rebuildError") + ": " + (rebuildState.message || ""),
              )
            : null,
        ),
      )
    }

    /* ------------------------------------------------------------------ */
    /* 地图                                                               */
    /* ------------------------------------------------------------------ */

    function MapView(props) {
      const p = props || {}
      const t = p.t
      const [input, setInput] = useState("")
      const [focus, setFocus] = useState("")
      const submit = function (event) {
        prevent(event)
        setFocus(input.trim())
      }
      const clear = function () {
        setInput("")
        setFocus("")
      }
      return h(
        "div",
        { className: "cbi-view" },
        h(
          "form",
          { className: "cbi-form", onSubmit: submit },
          h(
            "div",
            { className: "cbi-field" },
            h("label", { className: "cbi-label" }, t("map.focus")),
            h("input", {
              className: "cbi-input",
              type: "search",
              value: input,
              placeholder: t("map.focusPlaceholder"),
              onChange: function (event) {
                setInput(event.target.value)
              },
            }),
          ),
          h(
            "div",
            { className: "cbi-form-row" },
            h(Btn, { type: "submit", tone: "primary", glyph: "map" }, t("map.apply")),
            focus
              ? h(Btn, { tone: "ghost", onClick: clear }, t("common.clear"))
              : null,
          ),
        ),
        h(MapResults, { t: t, sessionId: p.sessionId, focus: focus, refreshToken: p.refreshToken }),
      )
    }

    function MapResults(props) {
      const p = props || {}
      const t = p.t
      const remote = useLoad(
        function () {
          return apiGet("/api/map", withSession(p.sessionId, { focus: p.focus || undefined }))
        },
        [p.sessionId, p.focus, p.refreshToken],
      )
      const gate = loadGate(t, remote, t("map.loadError"))
      if (gate) return gate
      const payload = isObject(remote.data) ? remote.data : {}
      const rows = mapEntryRows(payload)
      const omitted = mapOmitted(payload)
      return h(
        "div",
        { className: "cbi-view" },
        h(BudgetBar, { t: t, budget: budgetFacts(payload), truncated: truncatedOf(payload) }),
        h(Facts, {
          facts: [
            { key: "focus", label: p.focus ? t("map.focusEcho", { focus: p.focus }) : t("map.wholeRepo") },
            { key: "entries", label: t("map.entries"), value: rows.length },
            { key: "omitted", label: t("common.omitted"), value: omitted.files + omitted.symbols },
          ],
        }),
        h(
          Section,
          { title: t("map.entries"), count: rows.length > 0 ? fmtInt(rows.length) : null },
          h(DataTable, {
            t: t,
            rows: rows,
            emptyTitle: t("map.noEntries"),
            columns: [
              { key: "path", label: t("map.entries"), render: function (row) { return h(PathRef, { path: row.path, static: true }) } },
              { key: "language", label: t("common.language"), width: "78px" },
              {
                key: "symbolsText",
                label: t("overview.symbols"),
                width: "30%",
                render: function (row) {
                  return row.symbolCount === 0
                    ? h("span", { className: "cbi-muted" }, "—")
                    : h("span", { className: "cbi-mono", title: row.symbolsText }, clampText(row.symbolsText, 120))
                },
              },
            ],
          }),
        ),
        omitted.files > 0 || omitted.symbols > 0
          ? h(
              "div",
              { className: "cbi-more" },
              t("map.omittedSummary", { files: fmtInt(omitted.files), symbols: fmtInt(omitted.symbols) }),
            )
          : null,
      )
    }

    /* ------------------------------------------------------------------ */
    /* 搜索                                                               */
    /* ------------------------------------------------------------------ */

    function SearchView(props) {
      const p = props || {}
      const t = p.t
      const [input, setInput] = useState("")
      const [query, setQuery] = useState("")
      const submit = function (event) {
        prevent(event)
        setQuery(input.trim())
      }
      return h(
        "div",
        { className: "cbi-view" },
        h(
          "form",
          { className: "cbi-form", onSubmit: submit },
          h(
            "div",
            { className: "cbi-field" },
            h("label", { className: "cbi-label" }, t("search.query")),
            h("input", {
              className: "cbi-input",
              type: "search",
              value: input,
              placeholder: t("search.queryPlaceholder"),
              onChange: function (event) {
                setInput(event.target.value)
              },
            }),
          ),
          h(
            "div",
            { className: "cbi-form-row" },
            h(Btn, { type: "submit", tone: "primary", glyph: "search", disabled: input.trim().length === 0 }, t("search.submit")),
          ),
        ),
        query
          ? h(SearchResults, { t: t, sessionId: p.sessionId, query: query, refreshToken: p.refreshToken })
          : h(EmptyState, { title: t("search.prompt"), glyph: "search" }),
      )
    }

    function SearchResults(props) {
      const p = props || {}
      const t = p.t
      const remote = useLoad(
        function () {
          return apiGet("/api/search", withSession(p.sessionId, { query: p.query }))
        },
        [p.sessionId, p.query, p.refreshToken],
      )
      const gate = loadGate(t, remote, t("search.loadError"))
      if (gate) return gate
      const payload = isObject(remote.data) ? remote.data : {}
      const rows = searchResultRows(payload)
      return h(
        "div",
        { className: "cbi-view" },
        h(BudgetBar, { t: t, budget: budgetFacts(payload), truncated: truncatedOf(payload) }),
        h(Facts, {
          facts: [
            { key: "query", label: t("search.query"), value: clampText(p.query, 80) },
            { key: "total", label: t("search.total", { n: fmtInt(toNumber(payload.total, rows.length)) }) },
          ],
        }),
        h(
          Section,
          { title: t("search.results"), count: rows.length > 0 ? fmtInt(rows.length) : null },
          h(DataTable, {
            t: t,
            rows: rows,
            emptyTitle: t("search.noResults"),
            columns: [
              { key: "score", label: t("search.score"), className: "cbi-col-num", width: "52px", render: function (row) { return fmtNum(row.score, 2) } },
              {
                key: "symbol",
                label: t("context.symbol"),
                render: function (row) {
                  return h(
                    "span",
                    { title: row.symbol },
                    row.symbol ? h("span", { className: "cbi-mono" }, clampText(row.symbol, 64)) : h("span", { className: "cbi-muted" }, "—"),
                    row.kind ? h(Badge, { tone: "muted" }, row.kind) : null,
                  )
                },
              },
              { key: "path", label: t("common.path"), render: function (row) { return h(PathRef, { path: row.path, line: row.line, static: true }) } },
              { key: "match", label: t("search.match"), width: "30%", render: function (row) { return h("span", { className: "cbi-mono" }, clampText(row.match, 80) || "—") } },
            ],
          }),
        ),
      )
    }

    /* ------------------------------------------------------------------ */
    /* 依赖                                                               */
    /* ------------------------------------------------------------------ */

    function DependenciesView(props) {
      const p = props || {}
      const t = p.t
      const [targetInput, setTargetInput] = useState("")
      const [direction, setDirection] = useState("both")
      const [depth, setDepth] = useState("1")
      const [request, setRequest] = useState(null)
      const submit = function (event) {
        prevent(event)
        const target = targetInput.trim()
        if (!target) return
        setRequest({ target: target, direction: direction, depth: toNumber(depth, 1) })
      }
      return h(
        "div",
        { className: "cbi-view" },
        h(
          "form",
          { className: "cbi-form", onSubmit: submit },
          h(
            "div",
            { className: "cbi-field" },
            h("label", { className: "cbi-label" }, t("deps.target")),
            h("input", {
              className: "cbi-input",
              type: "search",
              value: targetInput,
              placeholder: t("deps.targetPlaceholder"),
              onChange: function (event) {
                setTargetInput(event.target.value)
              },
            }),
          ),
          h(
            "div",
            { className: "cbi-form-row" },
            h(
              "div",
              { className: "cbi-field cbi-field-inline" },
              h("label", { className: "cbi-label" }, t("deps.direction")),
              h(
                "select",
                {
                  className: "cbi-select",
                  value: direction,
                  onChange: function (event) {
                    setDirection(event.target.value)
                  },
                },
                h("option", { value: "both" }, t("deps.directionBoth")),
                h("option", { value: "imports" }, t("deps.directionImports")),
                h("option", { value: "dependents" }, t("deps.directionDependents")),
              ),
            ),
            h(
              "div",
              { className: "cbi-field cbi-field-inline" },
              h("label", { className: "cbi-label" }, t("deps.depth")),
              h(
                "select",
                {
                  className: "cbi-select",
                  value: depth,
                  onChange: function (event) {
                    setDepth(event.target.value)
                  },
                },
                ["1", "2", "3", "4", "5"].map(function (value) {
                  return h("option", { value: value, key: value }, value)
                }),
              ),
            ),
            h(Btn, { type: "submit", tone: "primary", glyph: "link", disabled: targetInput.trim().length === 0 }, t("deps.analyze")),
          ),
        ),
        request
          ? h(DependencyResults, {
              t: t,
              sessionId: p.sessionId,
              request: request,
              refreshToken: p.refreshToken,
            })
          : h(EmptyState, { title: t("deps.prompt"), glyph: "link" }),
        h(ImpactSection, { t: t, sessionId: p.sessionId, refreshToken: p.refreshToken }),
      )
    }

    function DependencyResults(props) {
      const p = props || {}
      const t = p.t
      const request = isObject(p.request) ? p.request : {}
      const remote = useLoad(
        function () {
          return apiGet(
            "/api/dependencies",
            withSession(p.sessionId, {
              target: request.target,
              direction: request.direction,
              depth: request.depth,
            }),
          )
        },
        [p.sessionId, request.target, request.direction, request.depth, p.refreshToken],
      )
      const gate = loadGate(t, remote, t("deps.loadError"))
      if (gate) return gate
      const payload = isObject(remote.data) ? remote.data : {}
      const nodes = dependencyNodeRows(payload)
      const edges = dependencyEdgeRows(payload)
      const target = dependencyTargetText(payload) || toText(request.target)
      const direction = toText(payload.direction) || toText(request.direction)
      return h(
        "div",
        { className: "cbi-view" },
        h(BudgetBar, { t: t, budget: budgetFacts(payload), truncated: truncatedOf(payload) }),
        h(Facts, {
          facts: [
            { key: "echo", label: t("deps.echo", { target: clampText(target, 60), direction: direction, depth: fmtInt(toNumber(payload.depth, request.depth)) }) },
            { key: "nodes", label: t("deps.nodes"), value: nodes.length },
            { key: "edges", label: t("deps.edges"), value: edges.length },
          ],
        }),
        h(
          Section,
          { title: t("deps.nodes"), count: nodes.length > 0 ? fmtInt(nodes.length) : null },
          h(DataTable, {
            t: t,
            rows: nodes,
            emptyTitle: t("deps.noNodes"),
            columns: [
              { key: "distance", label: t("deps.distance"), className: "cbi-col-num", width: "48px", render: function (row) { return row.distance === null ? "—" : fmtInt(row.distance) } },
              { key: "path", label: t("common.path"), render: function (row) { return row.path ? h(PathRef, { path: row.path, static: true }) : h("span", { className: "cbi-mono", title: row.id }, clampText(row.id, 56)) } },
              { key: "id", label: "id", width: "34%", render: function (row) { return h("span", { className: "cbi-mono cbi-muted", title: row.id }, clampText(row.id, 64)) } },
            ],
          }),
        ),
        h(
          Section,
          { title: t("deps.edges"), count: edges.length > 0 ? fmtInt(edges.length) : null },
          h(DataTable, {
            t: t,
            rows: edges,
            emptyTitle: t("deps.noEdges"),
            columns: [
              { key: "type", label: t("deps.type"), width: "62px" },
              {
                key: "status",
                label: t("deps.status"),
                width: "86px",
                render: function (row) {
                  return h(Badge, { tone: dependencyStatusTone(row.status), title: row.status }, row.status || "—")
                },
              },
              {
                key: "route",
                label: t("deps.from") + " → " + t("deps.to"),
                render: function (row) {
                  return h(
                    "span",
                    { className: "cbi-mono", title: row.from + " → " + row.to },
                    clampText(row.from, 40),
                    h("span", { className: "cbi-muted" }, " → "),
                    clampText(row.to, 40),
                  )
                },
              },
              { key: "evidence", label: t("deps.evidence"), width: "74px", render: function (row) { return h("span", { className: "cbi-muted" }, row.evidence || "—") } },
            ],
          }),
        ),
      )
    }

    function ImpactSection(props) {
      const p = props || {}
      const t = p.t
      const [input, setInput] = useState("")
      const [request, setRequest] = useState(null)
      const submit = function (event) {
        prevent(event)
        const files = splitCommaList(input)
        if (files.length === 0) return
        setRequest({ files: files })
      }
      return h(
        Section,
        {
          title: t("deps.impact"),
          actions: null,
        },
        h(
          "form",
          { className: "cbi-form", onSubmit: submit },
          h(
            "div",
            { className: "cbi-field" },
            h("label", { className: "cbi-label" }, t("deps.impactFiles")),
            h("input", {
              className: "cbi-input",
              type: "text",
              value: input,
              placeholder: t("deps.impactFilesPlaceholder"),
              onChange: function (event) {
                setInput(event.target.value)
              },
            }),
          ),
          h(
            "div",
            { className: "cbi-form-row" },
            h(Btn, { type: "submit", tone: "primary", glyph: "node", disabled: input.trim().length === 0 }, t("deps.impactRun")),
          ),
        ),
        request
          ? h(ImpactResults, { t: t, sessionId: p.sessionId, files: request.files, refreshToken: p.refreshToken })
          : null,
      )
    }

    function ImpactResults(props) {
      const p = props || {}
      const t = p.t
      const files = safeArray(p.files)
      const remote = useLoad(
        function () {
          return apiGet("/api/impact", withSession(p.sessionId, { files: files.join(",") }))
        },
        [p.sessionId, files.join(","), p.refreshToken],
      )
      const gate = loadGate(t, remote, t("deps.impactLoadError"))
      if (gate) return gate
      const payload = isObject(remote.data) ? remote.data : {}
      const facts = impactFacts(payload)
      return h(
        "div",
        { className: "cbi-view" },
        h(BudgetBar, { t: t, budget: budgetFacts(payload), truncated: facts.truncated }),
        facts.affectedFiles.length === 0 && facts.affectedSymbols.length === 0
          ? h(EmptyState, { title: t("deps.impactEmpty"), glyph: "check" })
          : null,
        facts.affectedFiles.length > 0
          ? h(
              Section,
              { title: t("deps.affectedFiles"), count: fmtInt(facts.affectedFiles.length) },
              h(DataTable, {
                t: t,
                rows: facts.affectedFiles,
                emptyTitle: t("deps.impactEmpty"),
                columns: [
                  { key: "path", label: t("deps.affectedFiles"), render: function (row) { return h(PathRef, { path: row.path, static: true }) } },
                  { key: "distance", label: t("deps.distance"), className: "cbi-col-num", width: "46px", render: function (row) { return row.distance === null ? "—" : fmtInt(row.distance) } },
                  { key: "confidence", label: t("deps.confidence"), width: "70px" },
                  { key: "reason", label: t("deps.reason"), width: "30%", render: function (row) { return h("span", { className: "cbi-muted" }, clampText(row.reason, 80) || "—") } },
                ],
              }),
            )
          : null,
        facts.affectedSymbols.length > 0
          ? h(
              Section,
              { title: t("deps.affectedSymbols"), count: fmtInt(facts.affectedSymbols.length) },
              h(DataTable, {
                t: t,
                rows: facts.affectedSymbols,
                emptyTitle: t("deps.impactEmpty"),
                columns: [
                  { key: "symbol", label: t("context.symbol"), render: function (row) { return h("span", { className: "cbi-mono", title: row.symbol }, clampText(row.symbol || row.id, 64)) } },
                  { key: "path", label: t("common.path"), render: function (row) { return h(PathRef, { path: row.path, static: true }) } },
                  { key: "confidence", label: t("deps.confidence"), width: "66px" },
                ],
              }),
            )
          : null,
      )
    }

    /* ------------------------------------------------------------------ */
    /* 上下文                                                             */
    /* ------------------------------------------------------------------ */

    function ContextView(props) {
      const p = props || {}
      const t = p.t
      const [task, setTask] = useState("")
      const [pathPrefix, setPathPrefix] = useState("")
      const [request, setRequest] = useState(null)
      const submit = function (event) {
        prevent(event)
        const value = task.trim()
        if (!value) return
        setRequest({ task: value, pathPrefix: pathPrefix.trim() })
      }
      return h(
        "div",
        { className: "cbi-view" },
        h(
          "form",
          { className: "cbi-form", onSubmit: submit },
          h(
            "div",
            { className: "cbi-field" },
            h("label", { className: "cbi-label" }, t("context.task")),
            h("textarea", {
              className: "cbi-textarea",
              rows: 3,
              value: task,
              placeholder: t("context.taskPlaceholder"),
              onChange: function (event) {
                setTask(event.target.value)
              },
            }),
          ),
          h(
            "div",
            { className: "cbi-field" },
            h("label", { className: "cbi-label" }, t("context.pathPrefix") + " · " + t("common.optional")),
            h("input", {
              className: "cbi-input",
              type: "text",
              value: pathPrefix,
              placeholder: t("context.pathPrefixPlaceholder"),
              onChange: function (event) {
                setPathPrefix(event.target.value)
              },
            }),
          ),
          h(
            "div",
            { className: "cbi-form-row" },
            h(Btn, { type: "submit", tone: "primary", glyph: "context", disabled: task.trim().length === 0 }, t("context.build")),
          ),
        ),
        request
          ? h(ContextResults, {
              t: t,
              sessionId: p.sessionId,
              request: request,
              refreshToken: p.refreshToken,
            })
          : h(EmptyState, { title: t("context.prompt"), glyph: "context" }),
      )
    }

    function ContextResults(props) {
      const p = props || {}
      const t = p.t
      const request = isObject(p.request) ? p.request : {}
      const remote = useLoad(
        function () {
          return apiGet(
            "/api/context",
            withSession(p.sessionId, { task: request.task, pathPrefix: request.pathPrefix || undefined }),
          )
        },
        [p.sessionId, request.task, request.pathPrefix, p.refreshToken],
      )
      const gate = loadGate(t, remote, t("context.loadError"))
      if (gate) return gate
      const payload = isObject(remote.data) ? remote.data : {}
      const items = contextItemRows(payload)
      const omitted = contextOmittedRows(payload)
      const bounded = boundedRows(items)
      return h(
        "div",
        { className: "cbi-view" },
        h(BudgetBar, { t: t, budget: budgetFacts(payload), truncated: truncatedOf(payload) }),
        h(Facts, {
          facts: [
            { key: "task", label: t("context.task"), value: clampText(toText(payload.task) || request.task, 80) },
            { key: "items", label: t("context.items"), value: items.length },
          ],
        }),
        h(
          Section,
          { title: t("context.items"), count: items.length > 0 ? fmtInt(items.length) : null },
          items.length === 0
            ? h(EmptyState, { title: t("context.noItems"), glyph: "context" })
            : h(
                "div",
                { className: "cbi-excerpt-list" },
                bounded.rows.map(function (item) {
                  return h(
                    "article",
                    { className: "cbi-excerpt", key: item.key },
                    h(
                      "header",
                      { className: "cbi-excerpt-head" },
                      h(PathRef, { path: item.path, line: item.startLine, endLine: item.endLine, static: true }),
                      item.kind ? h(Badge, { tone: "muted" }, item.kind) : null,
                      item.tokensEstimated !== null
                        ? h(Badge, { tone: "brand" }, t("common.tokens", { n: fmtInt(item.tokensEstimated) }))
                        : null,
                    ),
                    item.symbol ? h("div", { className: "cbi-excerpt-symbol cbi-mono" }, item.symbol) : null,
                    item.reason ? h("div", { className: "cbi-excerpt-reason" }, item.reason) : null,
                    item.excerpt ? h("pre", { className: "cbi-code" }, boundedExcerpt(item.excerpt, 18, 2400)) : null,
                  )
                }),
                bounded.omitted > 0
                  ? h("div", { className: "cbi-more" }, t("common.moreRows", { n: fmtInt(bounded.omitted) }))
                  : null,
              ),
        ),
        omitted.length > 0
          ? h(
              Section,
              {
                title: t("context.omitted"),
                count: t("context.omittedSummary", { n: fmtInt(omitted.length) }),
              },
              h(
                "ul",
                { className: "cbi-changes" },
                omitted.slice(0, MAX_ROWS).map(function (row) {
                  return h(
                    "li",
                    { key: row.key },
                    h(PathRef, { path: row.path, static: true }),
                    row.reason ? h("span", { className: "cbi-muted" }, " · " + row.reason) : null,
                  )
                }),
              ),
            )
          : null,
      )
    }

    /* ------------------------------------------------------------------ */
    /* 生成                                                               */
    /* ------------------------------------------------------------------ */

    function ExportView(props) {
      const p = props || {}
      const t = p.t
      const [writeRevision, setWriteRevision] = useState(0)
      const [writing, setWriting] = useState(false)
      const [written, setWritten] = useState(null)
      const [writeError, setWriteError] = useState(null)
      const preview = useLoad(
        function () {
          return apiGet("/api/export", withSession(p.sessionId))
        },
        [p.sessionId, p.refreshToken, writeRevision],
        { keepData: true },
      )
      const gitRemote = useLoad(
        function () {
          return apiGet("/api/git", withSession(p.sessionId))
        },
        [p.sessionId, p.refreshToken, writeRevision],
        { keepData: true },
      )
      const plan = isObject(preview.data) ? preview.data : {}
      const result = isObject(written) ? written : null
      const files = result ? safeArray(result.files) : safeArray(plan.files)
      const outDir = toText((result && result.outDir) || plan.outDir) || DEFAULT_EXPORT_DIR
      const rows = exportRowsFor(files)
      const counts = exportCounts(rows)
      const stale = result ? false : plan.stale === true
      const manifestFingerprint = toText((result && result.manifestFingerprint) || plan.manifestFingerprint)
      const git = gitFactsOf(gitRemote.data || plan.git)
      const write = function () {
        if (writing) return
        if (!confirmWrite(t("export.writeConfirm", { dir: outDir }))) return
        setWriting(true)
        setWriteError(null)
        apiPost("/api/export", exportWriteBody(p.sessionId), withSession(p.sessionId)).then(
          function (data) {
            setWriting(false)
            setWritten(isObject(data) ? data : {})
            setWriteRevision(function (value) {
              return value + 1
            })
            gitRemote.reload()
          },
          function (error) {
            setWriting(false)
            setWriteError({ message: messageOf(error), code: errorCodeOf(error) })
          },
        )
      }
      const gitBody = h(
        "div",
        { className: "cbi-view" },
        gitRemote.status === "error"
          ? h(ErrorBox, { t: t, title: t("export.gitLoadError"), error: gitRemote.error, onRetry: gitRemote.reload })
          : null,
        h(
          Section,
          { title: t("export.git") },
          git.available === false
            ? h(EmptyState, { title: t("export.gitUnavailable"), glyph: "warning" })
            : h(Facts, {
                facts: [
                  { key: "branch", label: t("export.gitBranch"), value: git.branch || "—" },
                  {
                    key: "dirty",
                    label: t("export.gitDirty"),
                    value: git.dirty ? t("export.gitDirty") : t("export.gitClean"),
                  },
                ],
              }),
          git.exportChanges.length > 0
            ? h(
                "div",
                null,
                h("div", { className: "cbi-more" }, t("export.gitChanges")),
                h(
                  "ul",
                  { className: "cbi-changes" },
                  git.exportChanges.slice(0, MAX_ROWS).map(function (line, index) {
                    return h("li", { key: "change-" + index }, line)
                  }),
                ),
              )
            : null,
          h(
            "div",
            { className: "cbi-command" },
            h(Glyph, { name: "file", size: 13 }),
            h("code", null, git.command),
            h(CopyButton, { t: t, text: git.command, label: t("common.copyCommand") }),
          ),
          h("div", { className: "cbi-more" }, t("export.noRun")),
        ),
      )
      return h(
        "div",
        { className: "cbi-view" },
        h(ViewLead, {
          title: t("export.title"),
          subtitle: t("export.subtitle", { dir: outDir }),
          actions: h(
            Btn,
            {
              tone: "primary",
              glyph: "export",
              disabled: writing,
              onClick: write,
              title: t("export.previewHint"),
            },
            writing ? t("export.writing") : t("export.write"),
          ),
        }),
        preview.status === "error"
          ? h(ErrorBox, { t: t, title: t("export.previewLoadError"), error: preview.error, onRetry: preview.reload })
          : null,
        h(
          Section,
          {
            title: t("export.preview"),
            actions: h(Btn, {
              size: "sm",
              glyph: "refresh",
              title: t("common.refresh"),
              onClick: function () {
                preview.reload()
                gitRemote.reload()
              },
            }),
          },
          h(Facts, {
            facts: [
              { key: "outDir", label: t("export.outDir"), value: outDir },
              { key: "count", label: t("export.previewFacts"), value: t("export.fileCount", { n: fmtInt(counts.total - counts.missing) }) },
              { key: "manifest", label: t("export.manifestFingerprint"), value: shortHash(manifestFingerprint) || "—", raw: manifestFingerprint },
            ],
          }),
          h(
            "div",
            { className: "cbi-facts" },
            stale
              ? h(Badge, { tone: "warn", title: t("export.staleMark") }, t("common.stale"))
              : h(Badge, { tone: "ok", title: t("export.freshMark") }, t("common.fresh")),
            h("span", { className: "cbi-more" }, t("export.previewHint")),
          ),
          h(
            "div",
            { className: "cbi-checklist" },
            rows.map(function (row) {
              return h(
                "div",
                { className: "cbi-check-row", key: row.key },
                h("span", { className: "cbi-check-name", title: row.path || row.name }, row.name),
                h(Badge, { tone: exportStatusTone(row.status) }, t(exportStatusLabelKey(row.status))),
                h("span", { className: "cbi-check-size" }, row.bytes === null ? "—" : fmtBytes(row.bytes)),
              )
            }),
          ),
          h(
            "div",
            { className: "cbi-write-bar" },
            h(
              Btn,
              { tone: "primary", glyph: "export", disabled: writing, onClick: write },
              writing ? t("export.writing") : t("export.write"),
            ),
            h("span", { className: "cbi-more" }, t("export.previewHint")),
          ),
          writeError
            ? h(ErrorBox, { t: t, title: t("export.writeError"), error: writeError })
            : null,
          result
            ? h(
                "div",
                { className: "cbi-facts" },
                h(Badge, { tone: "ok" }, t("export.writeDone", { n: fmtInt(counts.total - counts.missing) })),
                h("span", { className: "cbi-mono" }, shortHash(manifestFingerprint) || "—"),
              )
            : null,
        ),
        gitBody,
      )
    }

    /* ------------------------------------------------------------------ */
    /* Panel shell                                                        */
    /* ------------------------------------------------------------------ */

    function PanelHeader(props) {
      const p = props || {}
      const t = p.t
      const facts = stateFacts(p.state)
      const available = p.state !== null && p.state !== undefined
      return h(
        "header",
        { className: "cbi-header" },
        h(
          "div",
          { className: "cbi-brand" },
          h("span", { className: "cbi-brand-mark" }, h(PanelMark, { size: 17 })),
          h(
            "div",
            { className: "cbi-brand-text" },
            h("div", { className: "cbi-brand-title" }, t("panel.title")),
            h(
              "div",
              { className: "cbi-brand-meta" },
              facts.workspace
                ? h("span", { className: "cbi-chip", title: facts.root || t("header.workspaceTitle") }, facts.workspace)
                : h("span", { className: "cbi-chip cbi-badge-tone-muted", title: t("state.noSession") }, t("state.noSession")),
              facts.fingerprint
                ? h("span", { className: "cbi-chip cbi-mono", title: t("common.fingerprint") + " " + facts.fingerprint }, facts.fingerprint)
                : null,
              h(
                Badge,
                {
                  tone: facts.engineAvailable ? "ok" : "warn",
                  title: (facts.pythonVersion ? "Python " + facts.pythonVersion + " · " : "") + t("header.engineTitle"),
                },
                t(facts.engineAvailable ? "common.engineReady" : "common.engineUnavailable"),
              ),
              facts.exportsStale ? h(Badge, { tone: "warn", title: t("header.staleTitle") }, t("common.stale")) : null,
            ),
          ),
        ),
        h(
          "div",
          { className: "cbi-header-actions" },
          h(
            "div",
            { className: "cbi-lang", role: "group", "aria-label": t("common.language") },
            h(
              "button",
              {
                type: "button",
                className: "cbi-lang-btn",
                "aria-pressed": p.lang === "zh" ? "true" : "false",
                title: t("header.langTitle") + " · 中文",
                onClick: function () {
                  if (typeof p.onLang === "function") p.onLang("zh")
                },
              },
              "中",
            ),
            h(
              "button",
              {
                type: "button",
                className: "cbi-lang-btn",
                "aria-pressed": p.lang === "en" ? "true" : "false",
                title: t("header.langTitle") + " · English",
                onClick: function () {
                  if (typeof p.onLang === "function") p.onLang("en")
                },
              },
              "EN",
            ),
          ),
          h(Btn, {
            glyph: "refresh",
            iconOnly: true,
            title: t("header.refreshTitle"),
            disabled: p.refreshing === true,
            onClick: function () {
              if (typeof p.onRefresh === "function") p.onRefresh()
            },
          }),
        ),
      )
    }

    function TabBar(props) {
      const p = props || {}
      const t = p.t
      return h(
        "nav",
        { className: "cbi-tabs", role: "tablist", "aria-label": t("panel.title") },
        VIEWS.map(function (view) {
          return h(
            "button",
            {
              key: view.id,
              type: "button",
              role: "tab",
              className: "cbi-tab",
              "aria-selected": p.view === view.id ? "true" : "false",
              onClick: function () {
                if (typeof p.onSelect === "function") p.onSelect(view.id)
              },
            },
            h(Glyph, { name: view.glyph, size: 13 }),
            h("span", null, t(view.labelKey)),
          )
        }),
      )
    }

    function ViewRouter(props) {
      const p = props || {}
      const shared = {
        t: p.t,
        sessionId: p.sessionId,
        state: p.state,
        refreshToken: p.refreshToken,
        onNavigate: p.onNavigate,
      }
      switch (p.view) {
        case "map":
          return h(MapView, shared)
        case "search":
          return h(SearchView, shared)
        case "dependencies":
          return h(DependenciesView, shared)
        case "context":
          return h(ContextView, shared)
        case "export":
          return h(ExportView, shared)
        default:
          return h(OverviewView, shared)
      }
    }

    /**
     * The one panel component: the right-sidebar pane passes its standard
     * `sessionId`, the full-page fallback derives the most recently active
     * session from the standard `useSessions` hook when available.
     */
    function Panel(props) {
      const p = props || {}
      const [lang, setLangState] = useState(function () {
        return detectLang()
      })
      const t = useMemo(
        function () {
          return makeT(lang)
        },
        [lang],
      )
      const [view, setView] = useState("overview")
      const [refreshToken, setRefreshToken] = useState(0)
      const sessionId = typeof p.sessionId === "string" ? p.sessionId : ""
      const state = useLoad(
        function () {
          return apiGet("/api/state", withSession(sessionId))
        },
        [sessionId, refreshToken],
      )
      const chooseLang = function (next) {
        if (next !== "zh" && next !== "en") return
        if (next === lang) return
        writeLang(next)
        setLangState(next)
      }
      const refresh = function () {
        setRefreshToken(function (value) {
          return value + 1
        })
      }
      const activeView = viewById(view)
      const navigate = useCallback(function (next) {
        setView(viewById(next).id)
      }, [])
      const hasState = isObject(state.data)
      let content
      if (state.status === "error") {
        content = h(ErrorBox, {
          t: t,
          title: t("common.error"),
          error: state.error,
          onRetry: function () {
            state.reload()
          },
        })
      } else if (state.status === "loading" && !hasState) {
        content = h(Loading, { t: t, label: t("state.loadingWorkspace") })
      } else {
        content = h(ViewRouter, {
          view: activeView.id,
          t: t,
          sessionId: sessionId,
          state: hasState ? state.data : null,
          refreshToken: refreshToken,
          onNavigate: navigate,
        })
      }
      return h(
        "div",
        { className: "cbi-root" + (p.variant === "main" ? " cbi-root-main" : " cbi-root-pane") },
        h("style", null, STYLES),
        h(
          "div",
          { className: "cbi-shell" },
          h(PanelHeader, {
            t: t,
            lang: lang,
            state: hasState ? state.data : null,
            refreshing: state.status === "loading",
            onLang: chooseLang,
            onRefresh: function () {
              refresh()
              state.reload()
            },
          }),
          h(TabBar, { t: t, view: activeView.id, onSelect: setView }),
          h("div", { className: "cbi-content" }, h(PanelBoundary, { t: t, key: activeView.id }, content)),
          h(
            "footer",
            { className: "cbi-foot" },
            h("span", null, t("panel.footnote")),
            h("span", { className: "cbi-foot-mono" }, PKG_ID + " v" + VERSION),
          ),
        ),
      )
    }

    /* ------------------------------------------------------------------ */
    /* Registration components                                            */
    /* ------------------------------------------------------------------ */

    /** Sidebar panellist icon. */
    function PanelIcon(props) {
      const p = props || {}
      return h(PanelMark, { size: toNumber(p.size, 18) })
    }

    /** Right-sidebar pane body: session-scoped slots pass `sessionId`. */
    function PanePanel(props) {
      const p = props || {}
      const sessionId = typeof p.sessionId === "string" ? p.sessionId : ""
      return h(Panel, { sessionId: sessionId, variant: "pane" })
    }

    function useNoSessions() {
      return ""
    }

    /**
     * The main slot is root-scoped (no sessionId). Prefer an explicit prop,
     * otherwise read the standard `useSessions` selector hook when the host
     * provides one, falling back to a session-less request.
     */
    function usePanelSessionId(props) {
      const p = props || {}
      const hook = typeof p.useSessions === "function" ? p.useSessions : useNoSessions
      const derived = hook(selectRecentSession)
      const explicit = typeof p.sessionId === "string" ? p.sessionId : ""
      if (explicit) return explicit
      return typeof derived === "string" ? derived : ""
    }

    /** Full-page fallback panel registered in the `main` slot. */
    function MainPanel(props) {
      const p = props || {}
      const sessionId = usePanelSessionId(p)
      return h(Panel, { sessionId: sessionId, variant: "main" })
    }

    /** Guide/Start card that opens the tab; `open` is injected by the host plugin. */
    function GuideEntryCard(props) {
      const p = props || {}
      const t = typeof p.t === "function" ? p.t : makeT("zh")
      const title = typeof p.title === "string" && p.title.length > 0 ? p.title : t("guide.open")
      const description =
        typeof p.description === "string" && p.description.length > 0 ? p.description : t("guide.description")
      const open = typeof p.open === "function" ? p.open : null
      return h(
        "button",
        {
          type: "button",
          className: "cbi-guide-entry",
          "aria-label": t("guide.open"),
          onClick: function () {
            if (open) open()
          },
        },
        h("span", { className: "cbi-guide-title" }, h(PanelMark, { size: 16 }), h("span", null, title)),
        h("span", { className: "cbi-guide-desc" }, description),
      )
    }
