/**
 * dsh-codebase-intelligence — 05-apply
 *
 * Slot, tab and locale registration, the plugin object the module loader
 * mounts, and the pure `__test__` surface the headless unit suite evaluates in
 * a vm. Activation never throws: every registration is individually guarded so
 * the plugin works with only `slots` + `locale` present (no right-sidebar
 * services), and the fallback full panel is always registered.
 */

    /* ------------------------------------------------------------------ */
    /* Locale                                                             */
    /* ------------------------------------------------------------------ */

    /** Register the zh/en namespace on the shared locale service. */
    function contributeLocale(ctx) {
      const locale = ctx && ctx.locale
      if (!locale || typeof locale.register !== "function") return
      const run = function () {
        return locale.register(NS, { zh: DICTIONARIES.zh, en: DICTIONARIES.en })
      }
      try {
        if (typeof ctx.effect === "function") {
          ctx.effect(run, PKG_ID + ": dictionaries")
          return
        }
        run()
      } catch (error) {
        /* a locale service that refuses the namespace must not fail the panel */
      }
    }

    /** `t` for host-projected copy (panellist label, tab title, guide card). */
    function bindTranslator(ctx) {
      try {
        if (ctx && ctx.locale && typeof ctx.locale.bind === "function") {
          const bound = ctx.locale.bind(NS)
          if (typeof bound === "function") return bound
        }
      } catch (error) {
        /* fall back to the embedded Chinese dictionary */
      }
      return makeT("zh")
    }

    /* ------------------------------------------------------------------ */
    /* Fallback slots (always registered; DSH without right sidebar)      */
    /* ------------------------------------------------------------------ */

    function registerFallbackSlots(ctx, t) {
      const slots = ctx && ctx.slots
      if (!slots || typeof slots.inject !== "function" || typeof slots.register !== "function") return
      try {
        slots.inject("sidebar.panellist", function () {
          return slots.register(
            {
              name: "sidebar.panellist",
              id: NS,
              order: 26,
              label: function () {
                return t("panel.title")
              },
              locale: NS,
            },
            PanelIcon,
          )
        })
      } catch (error) {
        /* the sidebar slot set may be absent in a headless composition */
      }
      try {
        slots.inject("main", function () {
          return slots.register({ name: "main", key: NS, locale: NS }, MainPanel)
        })
      } catch (error) {
        /* same: the full panel is an independence fallback */
      }
    }

    /* ------------------------------------------------------------------ */
    /* Right-sidebar tab (optional; feature-detected)                     */
    /* ------------------------------------------------------------------ */

    /** Open the panel's tab in one session; a missing session is a no-op. */
    function openPanelIn(scope, sessionId) {
      try {
        const session = toText(sessionId)
        if (!session) return
        const sidebarRight = scope && scope.sidebarRight
        if (!sidebarRight || typeof sidebarRight.openTabIn !== "function") return
        sidebarRight.openTabIn(session, NS)
      } catch (error) {
        /* opening a tab must never throw into a click handler */
      }
    }

    /**
     * Register the tab type, its body and its Start-guide card. Runs only when
     * the host provides both `sidebarRightTabs` and `sidebarRight`.
     */
    function setupRightSidebar(scope, t) {
      if (!scope) return null
      const tabs = scope.sidebarRightTabs
      const slots = scope.slots
      if (!tabs || typeof tabs.register !== "function") return null
      if (!slots || typeof slots.inject !== "function" || typeof slots.register !== "function") return null
      const definition = {
        id: NS,
        kind: NS,
        multiple: false,
        title: function () {
          return t("panel.title")
        },
        guide: [
          {
            id: "open",
            order: 26,
            title: function () {
              return t("panel.title")
            },
            description: function () {
              return t("panel.guideDescription")
            },
          },
        ],
      }
      const run = function () {
        return tabs.register(definition)
      }
      try {
        if (typeof scope.effect === "function") {
          scope.effect(run, PKG_ID + ": sidebar tab type")
        } else {
          run()
        }
      } catch (error) {
        /* a duplicate id/kind belongs to another plugin; the fallback stays */
        return null
      }
      try {
        slots.inject("sidebar.right.pane.tab", function () {
          return slots.register({ name: "sidebar.right.pane.tab", key: NS, locale: NS }, PanePanel)
        })
      } catch (error) {
        /* without the body seat the type simply has no panel; never throw */
      }
      try {
        slots.inject("sidebar.right.tab.guide.entry", function () {
          return slots.register(
            {
              name: "sidebar.right.tab.guide.entry",
              key: NS,
              locale: NS,
              inject: function (sessionId) {
                return {
                  open: function () {
                    openPanelIn(scope, sessionId)
                  },
                }
              },
            },
            GuideEntryCard,
          )
        })
      } catch (error) {
        /* the guide seat is optional in older right-sidebar builds */
      }
      return definition
    }

    /** Optional injection: the callback only runs when both services exist. */
    function registerRightSidebar(ctx, t) {
      if (!ctx || typeof ctx.inject !== "function") return
      try {
        ctx.inject(["sidebarRightTabs", "sidebarRight"], function (scope) {
          try {
            setupRightSidebar(scope, t)
          } catch (error) {
            /* feature detection must degrade to the fallback panel silently */
          }
        })
      } catch (error) {
        /* a hostile/immature ctx.inject must not fail activation */
      }
    }

    /* ------------------------------------------------------------------ */
    /* Plugin activation                                                  */
    /* ------------------------------------------------------------------ */

    /**
     * Register the locale dictionary, the always-on fallback panel and, when the
     * host exposes them, the right-sidebar tab, pane body and guide entry.
     *
     * @param {object} ctx the plugin's client Cordis context
     */
    function apply(ctx) {
      if (!ctx || typeof ctx !== "object") return
      try { ensureGlobalStyles() } catch (error) { /* styles are best effort */ }
      try {
        contributeLocale(ctx)
      } catch (error) {
        /* locale is best effort */
      }
      const t = bindTranslator(ctx)
      try {
        registerFallbackSlots(ctx, t)
      } catch (error) {
        /* the fallback registration is defensive at every step */
      }
      try {
        registerRightSidebar(ctx, t)
      } catch (error) {
        /* right-sidebar services are optional collaborators */
      }
    }

    /* ------------------------------------------------------------------ */
    /* Plugin object and the pure test surface                            */
    /* ------------------------------------------------------------------ */

    const __test__ = {
      /* identity + protocol */
      NS: NS,
      PKG_ID: PKG_ID,
      VERSION: VERSION,
      API_BASE: API_BASE,
      REQ_HEADER: REQ_HEADER,
      LANG_KEY: LANG_KEY,
      DEFAULT_EXPORT_DIR: DEFAULT_EXPORT_DIR,
      GIT_FALLBACK_COMMAND: GIT_FALLBACK_COMMAND,
      EXPORT_FILES: EXPORT_FILES,
      EXPORT_STATUSES: EXPORT_STATUSES,
      VIEWS: VIEWS,
      MAX_ROWS: MAX_ROWS,
      MAX_IMPACT_FILES: MAX_IMPACT_FILES,
      MAX_BUNDLE_BYTES: MAX_BUNDLE_BYTES,
      TEXT_ENTRIES: TEXT_ENTRIES,
      DICTIONARIES: DICTIONARIES,
      STYLES: STYLES,
      /* language */
      makeT: makeT,
      readLang: readLang,
      writeLang: writeLang,
      detectLang: detectLang,
      /* generic helpers */
      safeArray: safeArray,
      isObject: isObject,
      toNumber: toNumber,
      toText: toText,
      messageOf: messageOf,
      errorCodeOf: errorCodeOf,
      unwrapEnvelope: unwrapEnvelope,
      basenameOf: basenameOf,
      shortHash: shortHash,
      clampText: clampText,
      boundedExcerpt: boundedExcerpt,
      boundedRows: boundedRows,
      pathLineOf: pathLineOf,
      displayValue: displayValue,
      prevent: prevent,
      fmtInt: fmtInt,
      fmtNum: fmtNum,
      fmtBytes: fmtBytes,
      /* HTTP */
      encodeQuery: encodeQuery,
      apiUrl: apiUrl,
      withSession: withSession,
      requestHeaders: requestHeaders,
      apiGet: apiGet,
      apiPost: apiPost,
      refreshBody: refreshBody,
      exportWriteBody: exportWriteBody,
      gitCommandOf: gitCommandOf,
      /* clipboard */
      copyText: copyText,
      legacyCopy: legacyCopy,
      confirmWrite: confirmWrite,
      /* payload models */
      budgetFacts: budgetFacts,
      truncatedOf: truncatedOf,
      indexFacts: indexFacts,
      repoStats: repoStats,
      languageRows: languageRows,
      directoryRows: directoryRows,
      entryPointRows: entryPointRows,
      parseIssuesOf: parseIssuesOf,
      stateFacts: stateFacts,
      overviewFacts: overviewFacts,
      mapEntryRows: mapEntryRows,
      mapOmitted: mapOmitted,
      searchResultRows: searchResultRows,
      dependencyNodeRows: dependencyNodeRows,
      dependencyEdgeRows: dependencyEdgeRows,
      dependencyStatusTone: dependencyStatusTone,
      dependencyTargetText: dependencyTargetText,
      impactFacts: impactFacts,
      splitCommaList: splitCommaList,
      contextItemRows: contextItemRows,
      contextOmittedRows: contextOmittedRows,
      normalizeExportStatus: normalizeExportStatus,
      exportStatusTone: exportStatusTone,
      exportStatusLabelKey: exportStatusLabelKey,
      exportRowsFor: exportRowsFor,
      exportCounts: exportCounts,
      gitFactsOf: gitFactsOf,
      selectRecentSession: selectRecentSession,
      viewById: viewById,
      /* graph explorer models */
      graphNodeRows: graphNodeRows,
      graphEdgeRows: graphEdgeRows,
      graphNodeTone: graphNodeTone,
      graphEdgeTone: graphEdgeTone,
      graphVisibleEdges: graphVisibleEdges,
      graphDegrees: graphDegrees,
      graphNodeMatches: graphNodeMatches,
      graphMatchMap: graphMatchMap,
      graphLayout: graphLayout,
      graphEdgeGeometry: graphEdgeGeometry,
      /* components (identity assertions in the headless suite) */
      components: {
        Panel: Panel,
        MainPanel: MainPanel,
        PanePanel: PanePanel,
        GuideEntryCard: GuideEntryCard,
        PanelIcon: PanelIcon,
        PanelBoundary: PanelBoundary,
        ViewRouter: ViewRouter,
      },
      /* registration internals (exposed for activation tests) */
      contributeLocale: contributeLocale,
      bindTranslator: bindTranslator,
      registerFallbackSlots: registerFallbackSlots,
      registerRightSidebar: registerRightSidebar,
      setupRightSidebar: setupRightSidebar,
      openPanelIn: openPanelIn,
      apply: apply,
    }

    const PLUGIN = {
      name: PKG_ID,
      inject: ["slots", "locale"],
      apply: apply,
      __test__: __test__,
    }

    return PLUGIN
  },
})
