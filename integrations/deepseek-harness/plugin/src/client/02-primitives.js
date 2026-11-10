/**
 * dsh-codebase-intelligence — 02-primitives
 *
 * Small presentational primitives shared by every view: icons, badges,
 * buttons, bounded tables, path:line citations, budget bars, loading/error/
 * empty states and the load hook. No view-specific logic lives here.
 */

    /* ------------------------------------------------------------------ */
    /* Artwork                                                            */
    /* ------------------------------------------------------------------ */

    /** The plugin mark: a code bracket pair joined to a dependency node. */
    function PanelMark(props) {
      const size = toNumber(props && props.size, 18)
      return h(
        "svg",
        {
          width: size,
          height: size,
          viewBox: "0 0 20 20",
          fill: "none",
          "aria-hidden": "true",
          focusable: "false",
          style: { display: "block" },
        },
        h("path", {
          d: "M6 6.2 3 10l3 3.8",
          stroke: "currentColor",
          strokeWidth: "1.6",
          strokeLinecap: "round",
          strokeLinejoin: "round",
        }),
        h("path", {
          d: "M14 6.2 17 10l-3 3.8",
          stroke: "currentColor",
          strokeWidth: "1.6",
          strokeLinecap: "round",
          strokeLinejoin: "round",
        }),
        h("circle", { cx: "10", cy: "6.4", r: "1.55", fill: "currentColor" }),
        h("circle", { cx: "7.1", cy: "13.1", r: "1.3", fill: "currentColor" }),
        h("circle", { cx: "12.9", cy: "13.1", r: "1.3", fill: "currentColor" }),
        h("path", {
          d: "M9.5 8.4 8.4 11.4M10.5 8.4l1.1 3M8.4 13.1h3.2",
          stroke: "currentColor",
          strokeWidth: "1.1",
          strokeLinecap: "round",
        }),
      )
    }

    const GLYPH_PATHS = {
      overview: [
        "M3.5 3.5h5v5h-5z",
        "M11.5 3.5h5v3h-5z",
        "M11.5 8.5h5v8h-5z",
        "M3.5 10.5h5v6h-5z",
      ],
      map: ["M2.5 4.5 7 3l6 2.2 4.5-1.6v11L13 16.2 7 14 2.5 15.6z", "M7 3v11M13 5.2v11"],
      search: ["M8.8 3.2a5.6 5.6 0 1 1 0 11.2 5.6 5.6 0 0 1 0-11.2Z", "M13 13l3.6 3.6"],
      link: [
        "M8.2 11.8 11.8 8.2",
        "M7 13a3.4 3.4 0 0 1 0-4.8l1.9-1.9",
        "M13 7a3.4 3.4 0 0 1 0 4.8l-1.9 1.9",
      ],
      context: ["M4 3.2h8.5L16 6.7v10.1H4z", "M12.5 3.4v3.4h3.4", "M6.6 10h6.8M6.6 12.5h6.8M6.6 15h4.2"],
      export: ["M10 3v9", "M6.6 8.8 10 12.2l3.4-3.4", "M3.6 14.4v2.2h12.8v-2.2"],
      refresh: ["M15.6 8.4A6 6 0 1 0 16 11.6", "M15.6 3.6v4.8h-4.8"],
      copy: ["M7 7h8.5v9.5H7z", "M12.2 6.8V3.5H3.5V12h3.5"],
      check: ["M4 10.4 8 14.4 16 6.2"],
      warning: ["M10 3.2 17.6 16.4H2.4z", "M10 7.4v4", "M10 13.6v.6"],
      alert: ["M10 3.2a7 7 0 1 1 0 14 7 7 0 0 1 0-14Z", "M10 6.6v4.6", "M10 13.4v.6"],
      chevron: ["M7.4 4.6 12.8 10l-5.4 5.4"],
      node: ["M10 3.2a2.2 2.2 0 1 1 0 4.4 2.2 2.2 0 0 1 0-4.4Z", "M4.4 13a2 2 0 1 1 0 4 2 2 0 0 1 0-4Z", "M15.6 13a2 2 0 1 1 0 4 2 2 0 0 1 0-4Z", "M9 7.4 5.4 12.6M11 7.4l3.6 5.2"],
      file: ["M5 3.2h7L15 6.2v10.6H5z", "M11.6 3.4v3H14.8"],
    }

    /** Tiny inline icon set (single currentColor stroke). */
    function Glyph(props) {
      const p = props || {}
      const name = typeof p.name === "string" ? p.name : "node"
      const paths = GLYPH_PATHS[name] || GLYPH_PATHS.node
      const size = toNumber(p.size, 14)
      return h(
        "svg",
        {
          width: size,
          height: size,
          viewBox: "0 0 20 20",
          fill: "none",
          "aria-hidden": "true",
          focusable: "false",
          style: { display: "block", flex: "none" },
        },
        paths.map((definition, index) =>
          h("path", {
            key: name + "-" + index,
            d: definition,
            stroke: "currentColor",
            strokeWidth: "1.5",
            strokeLinecap: "round",
            strokeLinejoin: "round",
          }),
        ),
      )
    }

    /* ------------------------------------------------------------------ */
    /* Atoms                                                              */
    /* ------------------------------------------------------------------ */

    function Badge(props) {
      const p = props || {}
      const tone = typeof p.tone === "string" && p.tone.length > 0 ? p.tone : "muted"
      return h("span", { className: "cbi-badge cbi-badge-tone-" + tone, title: p.title || undefined }, p.children)
    }

    function Btn(props) {
      const p = props || {}
      const classes = ["cbi-btn"]
      if (p.tone === "primary") classes.push("cbi-btn-primary")
      else if (p.tone === "ghost") classes.push("cbi-btn-ghost")
      else if (p.tone === "warn") classes.push("cbi-btn-warn")
      if (p.iconOnly === true) classes.push("cbi-btn-icon")
      if (p.size === "sm") classes.push("cbi-btn-sm")
      return h(
        "button",
        {
          type: p.type === "submit" ? "submit" : "button",
          className: classes.join(" "),
          title: p.title || undefined,
          disabled: p.disabled === true ? true : undefined,
          "aria-label": p.label || p.title || undefined,
          onClick: p.onClick || undefined,
        },
        p.glyph ? h(Glyph, { name: p.glyph, size: p.iconSize || 13 }) : null,
        p.children === undefined || p.children === null ? null : h("span", null, p.children),
      )
    }

    function Spinner() {
      return h("span", { className: "cbi-spinner", "aria-hidden": "true" })
    }

    function Loading(props) {
      const p = props || {}
      const t = p.t
      return h(
        "div",
        { className: "cbi-loading", role: "status", "aria-live": "polite" },
        h(Spinner, null),
        h("span", null, p.label || (typeof t === "function" ? t("common.loading") : "…")),
      )
    }

    function EmptyState(props) {
      const p = props || {}
      return h(
        "div",
        { className: "cbi-state" },
        p.glyph ? h(Glyph, { name: p.glyph, size: 22 }) : null,
        h("div", { className: "cbi-state-title" }, p.title),
        p.hint ? h("div", { className: "cbi-state-hint" }, p.hint) : null,
      )
    }

    /** Never-throw error box with the host error code and a retry action. */
    function ErrorBox(props) {
      const p = props || {}
      const t = p.t
      const error = isObject(p.error) ? p.error : { message: messageOf(p.error), code: "" }
      return h(
        "div",
        { className: "cbi-error", role: "alert" },
        h(
          "div",
          { className: "cbi-error-head" },
          h(Glyph, { name: "alert", size: 13 }),
          h("span", null, p.title || (typeof t === "function" ? t("common.error") : "Error")),
          error.code ? h(Badge, { tone: "danger" }, error.code) : null,
        ),
        h("div", { className: "cbi-error-message" }, error.message || "—"),
        typeof p.onRetry === "function"
          ? h(
              "div",
              { className: "cbi-error-actions" },
              h(Btn, { size: "sm", glyph: "refresh", onClick: p.onRetry }, typeof t === "function" ? t("common.retry") : "Retry"),
            )
          : null,
      )
    }

    function Section(props) {
      const p = props || {}
      return h(
        "section",
        { className: "cbi-section" },
        h(
          "header",
          { className: "cbi-section-head" },
          h(
            "h3",
            { className: "cbi-section-title" },
            p.title,
            p.count !== undefined && p.count !== null ? h("span", { className: "cbi-section-count" }, p.count) : null,
          ),
          p.actions ? h("div", { className: "cbi-section-actions" }, p.actions) : null,
        ),
        p.children,
      )
    }

    /** Copy-to-clipboard control with a transient confirmation label. */
    function CopyButton(props) {
      const p = props || {}
      const t = p.t
      const [copied, setCopied] = useState(false)
      const timerRef = useRef(null)
      useEffect(
        function () {
          return function () {
            if (timerRef.current) clearTimeout(timerRef.current)
          }
        },
        [],
      )
      const click = function () {
        copyText(p.text).then(function (ok) {
          if (!ok) return
          setCopied(true)
          if (timerRef.current) clearTimeout(timerRef.current)
          timerRef.current = setTimeout(function () {
            setCopied(false)
          }, 1600)
        })
      }
      const base = typeof t === "function" ? t("common.copy") : "Copy"
      const done = typeof t === "function" ? t("common.copied") : "Copied"
      return h(
        Btn,
        {
          size: p.size || "sm",
          glyph: copied ? "check" : "copy",
          title: p.label || base,
          onClick: click,
          tone: p.tone || "ghost",
        },
        copied ? done : p.label || base,
      )
    }

    /* ------------------------------------------------------------------ */
    /* Data presentation                                                  */
    /* ------------------------------------------------------------------ */

    /**
     * A compact table bounded to MAX_ROWS. Columns are `{key, label, render,
     * className, width}`; the caller may supply already-derived rows.
     */
    function DataTable(props) {
      const p = props || {}
      const columns = safeArray(p.columns)
      const bounded = boundedRows(p.rows)
      if (bounded.total === 0) {
        return h(EmptyState, { title: p.emptyTitle || "—", hint: p.emptyHint || "" })
      }
      const rows = bounded.rows
      return h(
        "div",
        { className: "cbi-table-block" },
        h(
          "div",
          { className: "cbi-table-wrap" },
          h(
            "table",
            { className: "cbi-table" },
            h(
              "thead",
              null,
              h(
                "tr",
                null,
                columns.map(function (column) {
                  return h(
                    "th",
                    {
                      key: column.key,
                      className: column.className || undefined,
                      style: column.width ? { width: column.width } : undefined,
                    },
                    column.label,
                  )
                }),
              ),
            ),
            h(
              "tbody",
              null,
              rows.map(function (row, rowIndex) {
                const key = row && row.key !== undefined && row.key !== null ? String(row.key) : "row-" + rowIndex
                return h(
                  "tr",
                  { key: key },
                  columns.map(function (column) {
                    const value = column.render ? column.render(row) : displayValue(row ? row[column.key] : "");
                    return h("td", { key: column.key, className: column.className || undefined }, value)
                  }),
                )
              }),
            ),
          ),
        ),
        bounded.omitted > 0
          ? h(
              "div",
              { className: "cbi-more" },
              typeof p.t === "function" ? p.t("common.moreRows", { n: fmtInt(bounded.omitted) }) : String(bounded.omitted) + " more",
            )
          : null,
      )
    }

    /** A path:line citation; a click copies the citation text. */
    function PathRef(props) {
      const p = props || {}
      const path = toText(p.path)
      if (!path) return h("span", { className: "cbi-muted" }, "—")
      const line = toNumber(p.line, null)
      const endLine = toNumber(p.endLine, null)
      const text =
        line === null
          ? path
          : endLine !== null && endLine > line
            ? path + ":" + line + "-" + endLine
            : path + ":" + line
      const staticRef = p.static === true
      return h(
        "span",
        {
          className: "cbi-pathref",
          title: text,
          "data-static": staticRef ? "true" : undefined,
          onClick: staticRef
            ? undefined
            : function () {
                void copyText(text)
              },
        },
        h("span", { className: "cbi-path" }, path),
        line === null
          ? null
          : h("span", { className: "cbi-line" }, endLine !== null && endLine > line ? ":" + line + "-" + endLine : ":" + line),
      )
    }

    /** Budget / truncation facts of one engine payload. */
    function BudgetBar(props) {
      const p = props || {}
      const t = p.t
      const budget = isObject(p.budget) ? p.budget : null
      if (!budget || (budget.maxTokens === null && budget.tokensEstimated === null && p.truncated !== true)) return null
      const max = toNumber(budget.maxTokens, null)
      const used = toNumber(budget.tokensEstimated, null)
      const percent = max !== null && used !== null && max > 0 ? Math.min(100, Math.round((used / max) * 100)) : 0
      return h(
        "div",
        { className: "cbi-budget", role: "status" },
        h("span", { className: "cbi-budget-label" }, t("budget.bar", { used: fmtInt(used), max: fmtInt(max) })),
        h(
          "span",
          { className: "cbi-budget-bar", "aria-hidden": "true" },
          h("span", { className: "cbi-budget-fill", style: { width: percent + "%" }, "data-over": percent >= 100 ? "true" : undefined }),
        ),
        budget.tokenEstimator ? h("span", { className: "cbi-mono" }, t("budget.estimator", { name: budget.tokenEstimator })) : null,
        p.truncated === true ? h(Badge, { tone: "warn" }, t("common.truncated")) : null,
      )
    }

    /** Inline key/value facts row. */
    function FactList(props) {
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
            h("span", { className: "cbi-fact-value" }, displayValue(fact.value)),
          )
        }),
      )
    }

    /* ------------------------------------------------------------------ */
    /* Data loading                                                       */
    /* ------------------------------------------------------------------ */

    /**
     * Run one async loader and expose `{status, data, error, reload}`.
     * `deps` is serialized so callers can pass plain values; the reload nonce
     * re-runs the loader on demand. Stale responses are dropped.
     */
    function useLoad(load, deps, options) {
      const opts = options || {}
      const [snapshot, setSnapshot] = useState({ status: "loading", data: null, error: null })
      const [nonce, setNonce] = useState(0)
      const key = JSON.stringify(deps === undefined ? [] : deps)
      const keepData = opts.keepData === true
      useEffect(
        function () {
          let alive = true
          setSnapshot(function (previous) {
            return { status: "loading", data: keepData ? previous.data : null, error: null }
          })
          let pending
          try {
            pending = Promise.resolve(load())
          } catch (error) {
            pending = Promise.reject(error)
          }
          pending.then(
            function (data) {
              if (!alive) return
              setSnapshot({ status: "ready", data: data === undefined ? {} : data, error: null })
            },
            function (error) {
              if (!alive) return
              setSnapshot({ status: "error", data: null, error: { message: messageOf(error), code: errorCodeOf(error) } })
            },
          )
          return function () {
            alive = false
          }
        },
        [key, nonce],
      )
      const reload = useCallback(function () {
        setNonce(function (value) {
          return value + 1
        })
      }, [])
      return { status: snapshot.status, data: snapshot.data, error: snapshot.error, reload: reload }
    }

    /** Contain one view's render failure without taking the whole panel down. */
    class PanelBoundary extends react.Component {
      constructor(props) {
        super(props)
        this.state = { failed: false }
        this.retry = this.retry.bind(this)
      }
      static getDerivedStateFromError() {
        return { failed: true }
      }
      componentDidCatch(error) {
        try {
          console.error("[dsh-codebase-intelligence] panel view crashed:", error)
        } catch (ignored) {
          /* console may be guarded */
        }
      }
      retry() {
        this.setState({ failed: false })
      }
      render() {
        const t = this.props ? this.props.t : null
        if (this.state.failed) {
          return h(
            "div",
            { className: "cbi-state" },
            h(Glyph, { name: "warning", size: 22 }),
            h("div", { className: "cbi-state-title" }, typeof t === "function" ? t("common.renderError") : "The panel failed to render"),
            h(Btn, { size: "sm", glyph: "refresh", onClick: this.retry }, typeof t === "function" ? t("common.retryRender") : "Render again"),
          )
        }
        return this.props ? this.props.children : null
      }
    }
