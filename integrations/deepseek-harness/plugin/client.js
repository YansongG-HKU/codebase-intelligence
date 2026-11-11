/**
 * dsh-codebase-intelligence — 00-head
 *
 * Loader wrapper, protocol constants, the zh/en dictionary source of truth,
 * language persistence, generic payload helpers, formatting and the HTTP layer
 * for the panel routes (PANEL_CONTRACT.md §3).
 *
 * The shipped client is one dependency-free classic script assembled by
 * scripts/build-client.mjs from the fragments in src/client/ in filename order.
 * React is the only import and it always comes from require("react"); the
 * wrapper opens here and closes in 05-apply.js.
 */
window.__ModuleLoader__.load({
  id: "dsh-codebase-intelligence",
  factory: (require) => {
    const react = require("react")
    const h = react.createElement
    const { useState, useEffect, useRef, useCallback, useMemo } = react

    /* ------------------------------------------------------------------ */
    /* Identity and protocol constants                                    */
    /* ------------------------------------------------------------------ */

    /** Locale namespace, panellist id, main-slot key, tab id and tab kind. */
    const NS = "codebase-intelligence"
    /** Package name: the client module id the DSH module loader validates. */
    const PKG_ID = "dsh-codebase-intelligence"
    const VERSION = "0.1.0"
    /** URL prefix of the host panel routes. */
    const API_BASE = "/dsh-codebase-intelligence"
    /** Same-origin marker every panel request must carry. */
    const REQ_HEADER = "x-dsh-codebase-intelligence"
    /** localStorage key of the panel's own language toggle. */
    const LANG_KEY = "dsh-codebase-intelligence.lang"
    const REQUEST_TIMEOUT_MS = 45_000
    /** Hard bound on rendered rows in every table and list. */
    const MAX_ROWS = 50
    /** The shipped bundle stays well below this size. */
    const MAX_BUNDLE_BYTES = 224 * 1024
    /** Default generation directory (the host may report a different one). */
    const DEFAULT_EXPORT_DIR = "docs/codebase-intelligence"

    /** The fixed generation file set, in contract order. */
    const EXPORT_FILES = [
      "overview.json",
      "repo-map.json",
      "graph.snapshot.json",
      "ARCHITECTURE.generated.md",
      "REPO_MAP.md",
      "dependencies.mmd",
      "CONTEXT_BRIEF.md",
      "manifest.json",
    ]

    /** Export file statuses the host reports; anything else renders as missing. */
    const EXPORT_STATUSES = ["created", "updated", "unchanged"]

    /** The six panel views, in tab order. */
    const VIEWS = [
      { id: "overview", labelKey: "view.overview", glyph: "overview" },
      { id: "map", labelKey: "view.map", glyph: "map" },
      { id: "graph", labelKey: "view.graph", glyph: "link" },
      { id: "search", labelKey: "view.search", glyph: "search" },
      { id: "dependencies", labelKey: "view.dependencies", glyph: "link" },
      { id: "context", labelKey: "view.context", glyph: "context" },
      { id: "export", labelKey: "view.export", glyph: "export" },
    ]

    /** Impact-analysis input bound (the engine caps files at 50). */
    const MAX_IMPACT_FILES = 50
    /** Suggestion shown in the export view; the host produces the authoritative command. */
    const GIT_FALLBACK_COMMAND = 'git add docs/codebase-intelligence && git commit -m "docs: refresh codebase intelligence snapshot"'

    /* ------------------------------------------------------------------ */
    /* Dictionary — every row keeps zh/en paired so the two stay in sync   */
    /* ------------------------------------------------------------------ */

    /* cbi-text-entries:begin */
    const TEXT_ENTRIES = [
      ["panel.title", "代码库情报", "Codebase Intelligence"],
      ["panel.subtitle", "结构 · 搜索 · 依赖 · 上下文 · 生成", "Structure · search · deps · context · export"],
      [
        "panel.footnote",
        "只读 · 面板不进入模型上下文 · 生成文件需要显式确认",
        "Read-only · outside the model context · writes require explicit confirmation",
      ],
      [
        "panel.guideDescription",
        "浏览仓库结构、搜索符号、构建任务上下文并生成确定性文档快照",
        "Browse structure, search symbols, build task context and generate the deterministic doc snapshot",
      ],
      ["common.refresh", "刷新", "Refresh"],
      ["common.refreshing", "刷新中…", "Refreshing…"],
      ["common.loading", "加载中…", "Loading…"],
      ["common.retry", "重试", "Retry"],
      ["common.copy", "复制", "Copy"],
      ["common.copied", "已复制", "Copied"],
      ["common.copyFailed", "复制失败", "Copy failed"],
      ["common.clear", "清空", "Clear"],
      ["common.cancel", "取消", "Cancel"],
      ["common.error", "读取失败", "Request failed"],
      ["common.empty", "暂无数据", "No data"],
      ["common.emptyHint", "这里还没有可显示的内容。", "Nothing to show here yet."],
      ["common.moreRows", "另有 {n} 条未显示", "{n} more rows not shown"],
      ["common.truncated", "已截断", "Truncated"],
      ["common.language", "语言", "Language"],
      ["common.unknown", "未知", "Unknown"],
      ["common.renderError", "面板渲染出错", "The panel failed to render"],
      ["common.retryRender", "重新渲染", "Render again"],
      ["common.copyPath", "复制路径", "Copy path"],
      ["common.copyCommand", "复制命令", "Copy command"],
      ["common.optional", "可选", "Optional"],
      ["common.notAvailable", "—", "—"],
      ["common.path", "路径", "Path"],
      ["common.omitted", "省略", "Omitted"],
      ["common.engineReady", "引擎可用", "Engine ready"],
      ["common.engineUnavailable", "引擎不可用", "Engine unavailable"],
      ["common.workspace", "工作区", "Workspace"],
      ["common.fingerprint", "索引指纹", "Index fingerprint"],
      ["common.pythonVersion", "Python {version}", "Python {version}"],
      ["common.tokens", "约 {n} tokens", "~{n} tokens"],
      ["common.stale", "快照过期", "Snapshot stale"],
      ["common.fresh", "快照最新", "Snapshot current"],
      ["header.refreshTitle", "刷新面板数据", "Refresh panel data"],
      ["header.langTitle", "切换面板语言", "Switch panel language"],
      ["header.fingerprintTitle", "索引指纹（短）", "Index fingerprint (short)"],
      ["header.engineTitle", "本地 Python 引擎状态", "Local Python engine status"],
      ["header.workspaceTitle", "会话工作区绝对路径", "Absolute workspace path"],
      ["header.staleTitle", "生成目录与当前索引不同步", "The export directory is out of sync with the index"],
      ["view.overview", "概览", "Overview"],
      ["view.graph", "项目图谱", "Code graph"],
      ["graph.root", "仓库", "Repository"],
      ["graph.help", "逐层展开目录、文件和符号；选中节点查看入向/出向关系，选中连线查看只读源码证据。", "Drill into folders, files and symbols. Select a node for incoming/outgoing relations or an edge for read-only source evidence."],
      ["graph.back", "返回上一层", "Back"],
      ["graph.previous", "上一页", "Previous page"],
      ["graph.next", "下一页", "Next page"],
      ["graph.empty", "当前范围没有可展示的节点", "No nodes in this scope"],
      ["graph.emptyHint", "换一个目录或使用刷新图谱重建快照。", "Try another directory or refresh the graph snapshot."],
      ["graph.edges", "关系与源码证据", "Relationships and source evidence"],
      ["graph.filter", "关系类型", "Relation type"],
      ["graph.all", "全部", "All"],
      ["graph.hidden", "未显示的关系", "Relationships not shown"],
      ["graph.noSource", "此关系没有源码位置", "No source location for this relationship"],
      ["graph.zoomIn", "放大", "Zoom in"],
      ["graph.refresh", "刷新图谱", "Refresh graph"],
      ["graph.refreshing", "正在重建…", "Rebuilding…"],
      ["graph.zoomOut", "缩小", "Zoom out"],
      ["graph.in", "调用方 / 入向", "Incoming"],
      ["graph.out", "被调用方 / 出向", "Outgoing"],
      ["graph.both", "双向", "Both directions"],
      ["graph.canvasLabel", "仓库关系图", "Repository relationship graph"],
      ["graph.searchPlaceholder", "在图谱中搜索节点…", "Search nodes in this graph…"],
      ["graph.searchCount", "匹配 {n} / {total} 个节点", "Matched {n} / {total} nodes"],
      ["graph.clearSearch", "清除搜索", "Clear search"],
      ["graph.showUnresolved", "显示未解析/启发式关系", "Show unresolved/heuristic relations"],
      ["graph.hideUnresolved", "隐藏未解析/启发式关系", "Hide unresolved/heuristic relations"],
      ["graph.fit", "适应", "Fit"],
      ["graph.stats", "显示 {shown} / {total} 个节点 · 可见关系 {edges} · 省略 {hidden}", "Showing {shown} / {total} nodes · {edges} visible relations · {hidden} omitted"],
      ["graph.inspector", "节点详情", "Node details"],
      ["graph.focusBadge", "焦点", "Focus"],
      ["graph.nodeKind", "类型", "Kind"],
      ["graph.nodePath", "路径", "Path"],
      ["graph.nodeLine", "行号", "Line"],
      ["graph.nodeDegree", "入向 / 出向", "In / out"],
      ["graph.enter", "展开节点", "Open node"],
      ["graph.viewSource", "查看源码", "View source"],
      ["graph.clearSelection", "取消选择", "Clear selection"],
      ["graph.relations", "关系", "Relations"],
      ["graph.noRelations", "此节点在当前页没有关系。", "This node has no relations on this page."],
      ["graph.evidence", "源码证据", "Source evidence"],
      ["graph.sourceExcerpt", "源码摘录", "Source excerpt"],
      ["graph.sourceLabel", "来源", "Source"],
      ["graph.selectHint", "选择节点或连线查看详情；双击目录、文件或符号可继续展开。", "Select a node or edge for details; double-click a directory, file or symbol to drill in."],
      ["graph.selectEdgeHint", "选择一条连线查看源码位置，或在上方关系列表中选择。", "Select an edge for its source location, or pick one from the relation list above."],
      ["graph.kind.dir", "目录", "Directory"],
      ["graph.kind.file", "文件", "File"],
      ["graph.kind.symbol", "符号", "Symbol"],
      ["graph.kind.unresolved", "未解析", "Unresolved"],
      ["graph.edge.resolved", "已解析", "Resolved"],
      ["graph.edge.heuristic", "启发式", "Heuristic"],
      ["graph.edge.unresolved", "未解析", "Unresolved"],
      ["graph.status.resolved", "已解析", "Resolved"],
      ["graph.status.ambiguous", "歧义", "Ambiguous"],
      ["graph.status.unresolved", "未解析", "Unresolved"],
      ["graph.status.external", "外部", "External"],
      ["graph.evidence.parser", "parser", "parser"],
      ["graph.evidence.resolver", "resolver", "resolver"],
      ["graph.evidence.heuristic", "heuristic", "heuristic"],
      ["graph.relation.imports", "导入", "Imports"],
      ["graph.relation.calls", "调用", "Calls"],
      ["graph.relation.inherits", "继承", "Inherits"],
      ["graph.relation.implements", "实现", "Implements"],
      ["graph.relation.references", "引用", "References"],
      ["graph.relation.contains", "包含", "Contains"],
      ["graph.relation.defines", "定义", "Defines"],
      ["graph.relation.other", "其他", "Other"],
      ["graph.source.cache", "来源：本地快照", "Source: local snapshot"],
      ["graph.source.repository", "来源：仓库快照", "Source: repository snapshot"],
      ["graph.source.built", "来源：即时构建", "Source: freshly built"],
      ["graph.source.refreshed", "来源：已刷新", "Source: refreshed"],
      ["view.map", "地图", "Map"],
      ["view.search", "搜索", "Search"],
      ["view.dependencies", "依赖", "Dependencies"],
      ["view.context", "上下文", "Context"],
      ["view.export", "生成", "Generate"],
      ["overview.files", "文件", "Files"],
      ["overview.symbols", "符号", "Symbols"],
      ["overview.relations", "关系", "Relations"],
      ["overview.languages", "语言分布", "Languages"],
      ["overview.topDirectories", "主要目录", "Top directories"],
      ["overview.entryPoints", "入口点", "Entry points"],
      ["overview.parseIssues", "解析问题", "Parse issues"],
      ["overview.index", "索引", "Index"],
      ["overview.policy", "扫描策略", "Policy"],
      ["overview.engine", "引擎", "Engine"],
      ["overview.exports", "生成目录", "Export directory"],
      ["overview.noLanguages", "未检测到语言", "No languages detected"],
      ["overview.noDirectories", "未发现目录", "No directories found"],
      ["overview.noEntryPoints", "未发现入口点", "No entry points found"],
      ["overview.noIssues", "无解析问题", "No parse issues"],
      ["overview.issuesCount", "{n} 个问题", "{n} issues"],
      ["overview.issueSample", "样例", "Sample"],
      ["overview.loadError", "概览读取失败", "Could not load the overview"],
      ["overview.rebuild", "重建索引", "Rebuild index"],
      ["overview.rebuilding", "正在重建…", "Rebuilding…"],
      ["overview.rebuildHint", "强制重新扫描工作区并刷新索引", "Force a rescan of the workspace and refresh the index"],
      ["overview.rebuildDone", "索引已重建", "Index rebuilt"],
      ["overview.rebuildError", "索引重建失败", "Index rebuild failed"],
      ["overview.exportMissing", "尚未生成", "Not generated yet"],
      ["overview.exportStale", "与索引不同步", "Out of sync with the index"],
      ["overview.exportFresh", "与索引一致", "In sync with the index"],
      ["overview.exportFiles", "{n} 个文件", "{n} files"],
      ["map.focus", "聚焦路径", "Focus path"],
      ["map.focusPlaceholder", "例如 src/app（留空表示全仓库）", "e.g. src/app (empty = whole repo)"],
      ["map.apply", "聚焦", "Apply"],
      ["map.entries", "条目", "Entries"],
      ["map.symbolCount", "{n} 个符号", "{n} symbols"],
      [
        "map.omittedSummary",
        "已省略 {files} 个文件、{symbols} 个符号",
        "{files} files and {symbols} symbols omitted",
      ],
      ["map.noEntries", "未发现条目", "No entries found"],
      ["map.loadError", "地图读取失败", "Could not load the map"],
      ["map.focusEcho", "聚焦：{focus}", "Focus: {focus}"],
      ["map.wholeRepo", "全仓库", "Whole repository"],
      ["search.query", "查询", "Query"],
      [
        "search.queryPlaceholder",
        "符号、路径、签名或文档关键字",
        "Symbol, path, signature or doc keyword",
      ],
      ["search.submit", "搜索", "Search"],
      ["search.total", "命中 {n} 条", "{n} matches"],
      ["search.results", "结果", "Results"],
      ["search.score", "分数", "Score"],
      ["search.match", "匹配", "Match"],
      ["search.noResults", "没有匹配结果", "No matches"],
      ["search.prompt", "输入关键词开始搜索", "Type a query to start searching"],
      ["search.loadError", "搜索失败", "Search failed"],
      ["deps.target", "目标", "Target"],
      ["deps.targetPlaceholder", "文件路径或符号 id", "File path or symbol id"],
      ["deps.direction", "方向", "Direction"],
      ["deps.directionBoth", "双向", "Both"],
      ["deps.directionImports", "依赖", "Imports"],
      ["deps.directionDependents", "被依赖", "Dependents"],
      ["deps.depth", "深度", "Depth"],
      ["deps.analyze", "分析", "Analyze"],
      ["deps.nodes", "节点", "Nodes"],
      ["deps.edges", "边", "Edges"],
      ["deps.status", "状态", "Status"],
      ["deps.type", "类型", "Type"],
      ["deps.evidence", "证据", "Evidence"],
      ["deps.from", "起点", "From"],
      ["deps.to", "指向", "To"],
      ["deps.distance", "距离", "Distance"],
      ["deps.noNodes", "未找到节点", "No nodes found"],
      ["deps.noEdges", "未找到边", "No edges found"],
      ["deps.prompt", "输入目标开始分析", "Enter a target to start analyzing"],
      ["deps.loadError", "依赖分析失败", "Dependency analysis failed"],
      [
        "deps.echo",
        "目标 {target} · {direction} · 深度 {depth}",
        "Target {target} · {direction} · depth {depth}",
      ],
      ["deps.impact", "影响分析", "Impact analysis"],
      ["deps.impactFiles", "变更文件", "Changed files"],
      [
        "deps.impactFilesPlaceholder",
        "逗号分隔的仓库相对路径",
        "Comma-separated repository-relative paths",
      ],
      ["deps.impactRun", "分析影响", "Analyze impact"],
      ["deps.impactEmpty", "未发现受影响的文件或符号", "No affected files or symbols found"],
      ["deps.confidence", "置信度", "Confidence"],
      ["deps.reason", "原因", "Reason"],
      ["deps.affectedFiles", "受影响文件", "Affected files"],
      ["deps.affectedSymbols", "受影响符号", "Affected symbols"],
      ["deps.impactLoadError", "影响分析失败", "Impact analysis failed"],
      ["context.task", "任务", "Task"],
      [
        "context.taskPlaceholder",
        "描述你要完成的任务，例如：给面板加入导出确认",
        "Describe the task, e.g. add an export confirmation to the panel",
      ],
      ["context.pathPrefix", "路径前缀", "Path prefix"],
      ["context.pathPrefixPlaceholder", "例如 src/client（可选）", "e.g. src/client (optional)"],
      ["context.build", "构建上下文", "Build context"],
      ["context.items", "片段", "Excerpts"],
      ["context.omitted", "未纳入", "Omitted"],
      ["context.prompt", "输入任务开始构建上下文", "Enter a task to build a context pack"],
      ["context.loadError", "上下文构建失败", "Context build failed"],
      ["context.reason", "入选原因", "Why selected"],
      ["context.symbol", "符号", "Symbol"],
      ["context.noItems", "没有可用的片段", "No excerpts available"],
      ["context.omittedSummary", "{n} 条未纳入", "{n} dropped"],
      ["context.lineRange", "L{start}–{end}", "L{start}–{end}"],
      ["export.title", "生成快照", "Generate snapshot"],
      ["export.subtitle", "确定性地把仓库结构写入 {dir}", "Write the repository structure deterministically into {dir}"],
      ["export.outDir", "生成目录", "Output directory"],
      ["export.preview", "预检", "Preview"],
      ["export.previewHint", "预检不会写入任何文件", "A preview writes nothing"],
      ["export.files", "文件", "Files"],
      ["export.status", "状态", "Status"],
      ["export.size", "大小", "Size"],
      ["export.created", "将新建", "Will create"],
      ["export.updated", "将更新", "Will update"],
      ["export.unchanged", "无变化", "Unchanged"],
      ["export.missing", "缺失", "Missing"],
      ["export.written", "已写入", "Written"],
      ["export.write", "写入文件", "Write files"],
      [
        "export.writeConfirm",
        "将把 {total} 个文件写入 {dir}。继续吗？",
        "This will write {total} files into {dir}. Continue?",
      ],
      ["export.writing", "正在写入…", "Writing…"],
      ["export.writeDone", "已写入 {n} 个文件", "Wrote {n} files"],
      ["export.writeError", "写入失败", "Write failed"],
      ["export.manifestFingerprint", "清单指纹", "Manifest fingerprint"],
      ["export.previewFacts", "预检结果", "Preview result"],
      ["export.git", "版本控制", "Git"],
      ["export.gitBranch", "分支", "Branch"],
      ["export.gitDirty", "有未提交变更", "Uncommitted changes"],
      ["export.gitClean", "目录内干净", "Directory is clean"],
      ["export.gitChanges", "目录内变更", "Changes under the directory"],
      ["export.gitCommand", "建议命令", "Suggested command"],
      ["export.gitUnavailable", "当前工作区不是 git 仓库", "This workspace is not a git repository"],
      ["export.noRun", "面板不会执行任何 git 命令；命令仅用于复制", "The panel never runs git; the command is copy-only"],
      ["export.previewLoadError", "预检失败", "Preview failed"],
      ["export.gitLoadError", "版本控制状态读取失败", "Could not read git status"],
      ["export.notGenerated", "尚未生成", "Not generated yet"],
      [
        "export.staleMark",
        "生成目录与索引不同步",
        "The export directory is out of sync with the index",
      ],
      ["export.freshMark", "生成目录与索引一致", "The export directory is in sync with the index"],
      ["export.fileCount", "{n} / {total} 个文件", "{n} / {total} files"],
      ["budget.bar", "预算 {used}/{max} tokens", "Budget {used}/{max} tokens"],
      ["budget.estimator", "估算器 {name}", "estimator {name}"],
      ["budget.truncated", "结果已按预算截断", "Result truncated to fit the budget"],
      ["budget.unknown", "预算未知", "Budget unknown"],
      ["guide.open", "打开 Codebase Intelligence", "Open Codebase Intelligence"],
      [
        "guide.description",
        "右侧栏面板：结构、搜索、依赖、上下文与生成",
        "Right sidebar panel: structure, search, dependencies, context and generation",
      ],
      ["state.noSession", "尚未绑定会话；使用最近活跃工作区", "No session bound; using the most recently active workspace"],
      ["state.workspaceUnavailable", "工作区暂不可用", "Workspace unavailable"],
      ["state.loadingWorkspace", "正在读取工作区…", "Reading the workspace…"],
    ]
    /* cbi-text-entries:end */

    const DICTIONARIES = { zh: {}, en: {} }
    for (let index = 0; index < TEXT_ENTRIES.length; index += 1) {
      const row = TEXT_ENTRIES[index]
      DICTIONARIES.zh[row[0]] = row[1]
      DICTIONARIES.en[row[0]] = row[2]
    }

    /* ------------------------------------------------------------------ */
    /* Language persistence (panel-local; DSH chrome uses ctx.locale)      */
    /* ------------------------------------------------------------------ */

    function storageOf() {
      try {
        if (typeof window !== "undefined" && window && window.localStorage) return window.localStorage
      } catch (error) {
        /* storage can be unavailable in hardened browsers */
      }
      return null
    }

    function readLang() {
      try {
        const storage = storageOf()
        if (!storage) return ""
        const value = storage.getItem(LANG_KEY)
        if (value === "zh" || value === "en") return value
      } catch (error) {
        /* fall through to the default */
      }
      return ""
    }

    function writeLang(lang) {
      if (lang !== "zh" && lang !== "en") return
      try {
        const storage = storageOf()
        if (storage) storage.setItem(LANG_KEY, lang)
      } catch (error) {
        /* a full/denied store must not break the panel */
      }
    }

    /** Chinese is the panel default; the toggle persists an explicit choice. */
    function detectLang() {
      return readLang() || "zh"
    }

    function makeT(lang) {
      const dictionary = DICTIONARIES[lang] || DICTIONARIES.zh
      return function t(key, vars) {
        let text = dictionary[key] !== undefined ? dictionary[key] : String(key)
        if (vars && typeof text === "string") {
          const names = Object.keys(vars)
          for (let index = 0; index < names.length; index += 1) {
            const name = names[index]
            text = text.split("{" + name + "}").join(String(vars[name]))
          }
        }
        return text
      }
    }

    /* ------------------------------------------------------------------ */
    /* Generic helpers (framework-free; exposed through __test__)          */
    /* ------------------------------------------------------------------ */

    function safeArray(value) {
      return Array.isArray(value) ? value : []
    }

    function isObject(value) {
      return Boolean(value) && typeof value === "object" && !Array.isArray(value)
    }

    function toNumber(value, fallback) {
      if (value === null || value === undefined || value === "") return fallback
      const parsed = Number(value)
      return Number.isFinite(parsed) ? parsed : fallback
    }

    function toText(value) {
      if (value === null || value === undefined) return ""
      return typeof value === "string" ? value : String(value)
    }

    function messageOf(error) {
      if (!error) return ""
      if (typeof error === "string") return error
      if (error.message) return String(error.message)
      return String(error)
    }

    function errorCodeOf(error) {
      if (error && typeof error.code === "string" && error.code.length > 0) return error.code
      return ""
    }

    function unwrapEnvelope(payload) {
      if (isObject(payload) && payload.ok === true) {
        return payload.data === undefined ? {} : payload.data
      }
      return payload === null || payload === undefined ? {} : payload
    }

    function basenameOf(path) {
      const value = toText(path).trim()
      if (!value) return ""
      const parts = value.split(/[\\/]+/u).filter((part) => part.length > 0)
      if (parts.length === 0) return value
      return parts[parts.length - 1]
    }

    /** Short stable digest for the header: the first 12 characters of a hash. */
    function shortHash(value) {
      const text = toText(value).trim()
      if (text.length <= 16) return text
      return text.slice(0, 12)
    }

    function clampText(value, max) {
      const text = toText(value)
      const limit = toNumber(max, 160)
      if (limit <= 0 || text.length <= limit) return text
      return text.slice(0, Math.max(1, limit - 1)) + "…"
    }

    function boundedExcerpt(value, maxLines, maxChars) {
      const text = toText(value)
      const lineLimit = Math.max(1, Math.floor(toNumber(maxLines, 18)))
      const charLimit = Math.max(16, Math.floor(toNumber(maxChars, 2400)))
      const lines = text.split(/\r?\n/u)
      let out = lines.slice(0, lineLimit).join("\n")
      let clipped = lines.length > lineLimit
      if (out.length > charLimit) {
        out = out.slice(0, charLimit)
        clipped = true
      }
      return clipped ? out + "\n…" : out
    }

    /** Bound one list to MAX_ROWS (or an explicit limit) and report the remainder. */
    function boundedRows(list, limit) {
      const rows = safeArray(list)
      const max = typeof limit === "number" && limit > 0 ? Math.floor(limit) : MAX_ROWS
      return {
        rows: rows.slice(0, max),
        total: rows.length,
        omitted: Math.max(0, rows.length - max),
      }
    }

    /** "path:line" citation text for anything carrying a path + line. */
    function pathLineOf(item) {
      if (!isObject(item)) return ""
      const path = toText(item.path)
      if (!path) return ""
      const line = toNumber(item.line, toNumber(item.startLine, null))
      return line === null ? path : path + ":" + line
    }

    function displayValue(value) {
      if (value === null || value === undefined || value === "") return "—"
      if (typeof value === "boolean") return value ? "true" : "false"
      if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—"
      if (typeof value === "string") return value
      try {
        return clampText(JSON.stringify(value), 160)
      } catch (error) {
        return "—"
      }
    }

    function prevent(event) {
      try {
        if (event && typeof event.preventDefault === "function") event.preventDefault()
      } catch (error) {
        /* synthetic events may be frozen */
      }
    }

    /* ------------------------------------------------------------------ */
    /* Formatting                                                         */
    /* ------------------------------------------------------------------ */

    function fmtInt(value) {
      const number = toNumber(value, null)
      if (number === null) return "—"
      const rounded = Math.round(number)
      try {
        return new Intl.NumberFormat("en-US").format(rounded)
      } catch (error) {
        return String(rounded)
      }
    }

    function fmtNum(value, digits) {
      const number = toNumber(value, null)
      if (number === null) return "—"
      const places = Math.max(0, Math.floor(toNumber(digits, 2)))
      const factor = Math.pow(10, places)
      return String(Math.round(number * factor) / factor)
    }

    function fmtBytes(value) {
      const number = toNumber(value, null)
      if (number === null || number < 0) return "—"
      if (number < 1024) return fmtInt(number) + " B"
      if (number < 1024 * 1024) return (number / 1024).toFixed(1) + " KB"
      return (number / (1024 * 1024)).toFixed(1) + " MB"
    }

    /* ------------------------------------------------------------------ */
    /* HTTP: same-origin, marker header, {ok,data} envelope (§3)          */
    /* ------------------------------------------------------------------ */

    function encodeQuery(params) {
      if (!isObject(params)) return ""
      const parts = []
      const keys = Object.keys(params)
      for (let index = 0; index < keys.length; index += 1) {
        const key = keys[index]
        const value = params[key]
        if (value === undefined || value === null || value === "") continue
        parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(value)))
      }
      return parts.join("&")
    }

    function apiUrl(path, params) {
      const route = toText(path)
      const normalized = route.startsWith("/") ? route : "/" + route
      const query = encodeQuery(params)
      return API_BASE + normalized + (query ? "?" + query : "")
    }

    function withSession(sessionId, params) {
      const merged = {}
      const session = toText(sessionId)
      if (session.length > 0) merged.session = session
      if (isObject(params)) {
        const keys = Object.keys(params)
        for (let index = 0; index < keys.length; index += 1) {
          const key = keys[index]
          if (params[key] !== undefined) merged[key] = params[key]
        }
      }
      return merged
    }

    function requestHeaders(extra) {
      const headers = {}
      headers[REQ_HEADER] = "1"
      if (isObject(extra)) {
        const keys = Object.keys(extra)
        for (let index = 0; index < keys.length; index += 1) headers[keys[index]] = extra[keys[index]]
      }
      return headers
    }

    async function apiRequest(path, options) {
      const opts = options || {}
      const hasBody = opts.body !== undefined
      const headers = requestHeaders(hasBody ? { "content-type": "application/json" } : null)
      const timeoutMs = toNumber(opts.timeoutMs, REQUEST_TIMEOUT_MS)
      const controller = typeof AbortController === "function" ? new AbortController() : null
      let timer = null
      if (controller && timeoutMs > 0) timer = setTimeout(() => controller.abort(), timeoutMs)
      let response
      try {
        response = await fetch(apiUrl(path, opts.params), {
          method: opts.method || "GET",
          headers: headers,
          body: hasBody ? JSON.stringify(opts.body) : undefined,
          cache: "no-store",
          signal: controller ? controller.signal : undefined,
        })
      } catch (error) {
        if (timer) clearTimeout(timer)
        const failure = new Error(messageOf(error) || "network request failed")
        failure.code = error && error.name === "AbortError" ? "timeout" : "network"
        throw failure
      }
      if (timer) clearTimeout(timer)
      let payload = null
      try {
        payload = await response.json()
      } catch (error) {
        payload = null
      }
      if (!response.ok || (isObject(payload) && payload.ok === false)) {
        const message = isObject(payload) && payload.message ? String(payload.message) : "HTTP " + response.status
        const failure = new Error(message)
        failure.code = isObject(payload) && payload.code ? String(payload.code) : "http_" + response.status
        throw failure
      }
      return unwrapEnvelope(payload)
    }

    function apiGet(path, params, options) {
      return apiRequest(path, Object.assign({}, options || {}, { method: "GET", params: params }))
    }

    function apiPost(path, body, params, options) {
      return apiRequest(
        path,
        Object.assign({}, options || {}, { method: "POST", params: params, body: body === undefined ? {} : body }),
      )
    }

    /** POST /api/refresh body: `{session}` (omitted when no session is bound). */
    function refreshBody(sessionId) {
      const session = toText(sessionId)
      return session.length > 0 ? { session: session } : {}
    }

    /** POST /api/export body: `{session, confirm:true}`. */
    function exportWriteBody(sessionId) {
      const session = toText(sessionId)
      const body = {}
      if (session.length > 0) body.session = session
      body.confirm = true
      return body
    }

    /** The export command shown after a write; the host command wins when present. */
    function gitCommandOf(git) {
      if (isObject(git) && typeof git.command === "string" && git.command.length > 0) return git.command
      return GIT_FALLBACK_COMMAND
    }

    /* ------------------------------------------------------------------ */
    /* Clipboard (must never throw; the fallback keeps old engines working)*/
    /* ------------------------------------------------------------------ */

    function legacyCopy(text) {
      try {
        if (typeof document === "undefined" || !document || typeof document.createElement !== "function") return false
        const area = document.createElement("textarea")
        area.value = text
        area.setAttribute("readonly", "readonly")
        area.style.position = "fixed"
        area.style.opacity = "0"
        document.body.appendChild(area)
        area.select()
        const ok = typeof document.execCommand === "function" ? document.execCommand("copy") === true : false
        document.body.removeChild(area)
        return ok
      } catch (error) {
        return false
      }
    }

    function copyText(value) {
      const text = toText(value)
      if (!text) return Promise.resolve(false)
      try {
        if (
          typeof navigator !== "undefined" &&
          navigator &&
          navigator.clipboard &&
          typeof navigator.clipboard.writeText === "function"
        ) {
          return Promise.resolve(navigator.clipboard.writeText(text)).then(
            () => true,
            () => legacyCopy(text),
          )
        }
      } catch (error) {
        /* fall through to the legacy path */
      }
      return Promise.resolve(legacyCopy(text))
    }

    /** Explicit write confirmation; when confirm() is unavailable the answer is no. */
    function confirmWrite(message) {
      try {
        if (typeof window !== "undefined" && window && typeof window.confirm === "function") {
          return window.confirm(message) === true
        }
      } catch (error) {
        /* treat a throwing dialog as a refusal */
      }
      return false
    }

/**
 * dsh-codebase-intelligence — 01-styles
 *
 * One embedded stylesheet for the panel. Every selector is namespaced under
 * `.cbi-*`, no global CSS and no variable overrides: the theme is expressed as
 * DSH design tokens with safe light-theme fallbacks, so claude-mode and every
 * other DSH theme style the panel without any hard dependency.
 */

    const STYLES = `
.cbi-root,
.cbi-guide-entry {
  --cbi-bg: var(--dsw-alias-bg-base, #fbfbfa);
  --cbi-layer1: var(--dsw-alias-bg-layer-1, #ffffff);
  --cbi-layer2: var(--dsw-alias-bg-layer-2, #f4f4f1);
  --cbi-layer3: var(--dsw-alias-bg-layer-3, #ececea);
  --cbi-border: var(--dsw-alias-border-l1, rgba(20, 20, 20, 0.10));
  --cbi-border2: var(--dsw-alias-border-l2, rgba(20, 20, 20, 0.16));
  --cbi-border3: var(--dsw-alias-border-l3, rgba(20, 20, 20, 0.24));
  --cbi-ink: var(--dsw-alias-label-primary, #1a1a1a);
  --cbi-ink2: var(--dsw-alias-label-secondary, #4b4b47);
  --cbi-ink3: var(--dsw-alias-label-tertiary, #7d7d76);
  --cbi-caption: var(--dsw-alias-label-caption, #8b8b84);
  --cbi-brand: var(--dsw-alias-brand-primary, #2c5f8a);
  --cbi-on-brand: var(--dsw-alias-label-primary-inverted, #ffffff);
  --cbi-hover: var(--dsw-alias-interactive-bg-hover, rgba(20, 20, 20, 0.05));
  --cbi-ok: var(--dsw-alias-state-success-primary, #2f7d5b);
  --cbi-warn: var(--dsw-alias-state-warn-primary, #9a6a15);
  --cbi-danger: var(--dsw-alias-state-error-primary, #b03a2e);
  --cbi-radius: var(--dsw-radius-sm, 6px);
  --cbi-radius-lg: var(--dsw-radius-lg, 12px);
  --cbi-shadow: var(--dsw-shadow-lv1, 0 1px 2px rgba(0, 0, 0, 0.06));
  --cbi-sans: var(--dsw-alias-font-family-sans, "Segoe UI Variable Text", "Segoe UI", -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif);
  --cbi-mono: var(--dsw-alias-font-family-mono, ui-monospace, "SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  width: 100%;
  overflow: hidden;
  background: var(--cbi-bg);
  color: var(--cbi-ink);
  font-family: var(--cbi-sans);
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
  -webkit-font-smoothing: antialiased;
}
.cbi-root *,
.cbi-root *::before,
.cbi-root *::after { box-sizing: border-box; }
.cbi-root button,
.cbi-root input,
.cbi-root select,
.cbi-root textarea { font: inherit; color: inherit; }
.cbi-root:focus-visible { outline: none; }

.cbi-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  width: 100%;
}
.cbi-root-main .cbi-shell {
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 20px;
}

/* Header ------------------------------------------------------------- */
.cbi-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--cbi-border);
  background: var(--cbi-layer1);
  flex: none;
}
.cbi-root-main .cbi-header { padding: 16px 0 12px; background: transparent; }
.cbi-brand { display: flex; align-items: flex-start; gap: 8px; min-width: 0; }
.cbi-brand-mark {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--cbi-radius);
  background: var(--cbi-layer2);
  border: 1px solid var(--cbi-border);
  color: var(--cbi-brand);
}
.cbi-brand-text { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.cbi-brand-title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--cbi-ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cbi-brand-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px; min-width: 0; }
.cbi-header-actions { display: flex; align-items: center; gap: 4px; flex: none; }
.cbi-lang {
  display: inline-flex;
  border: 1px solid var(--cbi-border2);
  border-radius: var(--cbi-radius);
  overflow: hidden;
}
.cbi-lang-btn {
  border: 0;
  background: transparent;
  color: var(--cbi-ink2);
  padding: 2px 6px;
  font-size: 11px;
  line-height: 16px;
  cursor: pointer;
}
.cbi-lang-btn[aria-pressed="true"] { background: var(--cbi-brand); color: var(--cbi-on-brand); }
@media (hover: hover) { .cbi-lang-btn:hover { background: var(--cbi-hover); } }
.cbi-lang-btn[aria-pressed="true"]:hover { background: var(--cbi-brand); }

/* Tab bar ------------------------------------------------------------ */
.cbi-tabs {
  display: flex;
  gap: 2px;
  flex: none;
  overflow-x: auto;
  padding: 6px 8px 0;
  border-bottom: 1px solid var(--cbi-border);
  background: var(--cbi-layer1);
  scrollbar-width: none;
}
.cbi-root-main .cbi-tabs { padding: 4px 0 0; background: transparent; border-bottom-color: var(--cbi-border2); }
.cbi-tabs::-webkit-scrollbar { display: none; }
.cbi-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  margin-bottom: -1px;
  padding: 6px 9px 7px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--cbi-ink3);
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
  border-radius: var(--cbi-radius) var(--cbi-radius) 0 0;
}
@media (hover: hover) { .cbi-tab:hover { color: var(--cbi-ink); background: var(--cbi-hover); } }
.cbi-tab[aria-selected="true"] { color: var(--cbi-ink); border-bottom-color: var(--cbi-brand); font-weight: 600; }
.cbi-tab:focus-visible { outline: 2px solid var(--cbi-brand); outline-offset: -2px; }

/* Content and views -------------------------------------------------- */
.cbi-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 10px 12px 28px;
  scrollbar-width: thin;
}
.cbi-root-main .cbi-content { padding: 14px 0 32px; }
.cbi-view { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.cbi-root-main .cbi-view { gap: 14px; }

.cbi-view-lead {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.cbi-view-lead h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--cbi-ink);
}
.cbi-view-lead p { margin: 2px 0 0; font-size: 12px; color: var(--cbi-ink3); }

/* Section ------------------------------------------------------------ */
.cbi-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  border: 1px solid var(--cbi-border);
  border-radius: var(--cbi-radius-lg);
  background: var(--cbi-layer1);
  padding: 9px 10px;
}
.cbi-root-main .cbi-section { padding: 14px 16px; }
.cbi-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.cbi-section-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--cbi-ink2);
  text-transform: uppercase;
}
.cbi-section-count { font-size: 11px; color: var(--cbi-ink3); font-weight: 400; letter-spacing: 0; text-transform: none; }
.cbi-section-actions { display: flex; align-items: center; gap: 4px; flex: none; }

/* Stats -------------------------------------------------------------- */
.cbi-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(78px, 1fr));
  gap: 6px;
}
.cbi-stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 7px 8px;
  border: 1px solid var(--cbi-border);
  border-radius: var(--cbi-radius);
  background: var(--cbi-layer2);
  min-width: 0;
}
.cbi-stat-label { font-size: 10px; color: var(--cbi-ink3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cbi-stat-value { font-size: 15px; font-weight: 600; color: var(--cbi-ink); font-variant-numeric: tabular-nums; }

/* Chips and badges --------------------------------------------------- */
.cbi-chip,
.cbi-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  max-width: 100%;
  padding: 0 5px;
  border-radius: 4px;
  border: 1px solid var(--cbi-border2);
  background: var(--cbi-layer2);
  color: var(--cbi-ink2);
  font-size: 10px;
  line-height: 16px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}
.cbi-badge-tone-ok { color: var(--cbi-ok); border-color: var(--cbi-ok); background: transparent; }
.cbi-badge-tone-warn { color: var(--cbi-warn); border-color: var(--cbi-warn); background: transparent; }
.cbi-badge-tone-danger { color: var(--cbi-danger); border-color: var(--cbi-danger); background: transparent; }
.cbi-badge-tone-brand { color: var(--cbi-on-brand); border-color: var(--cbi-brand); background: var(--cbi-brand); }
.cbi-badge-tone-muted { color: var(--cbi-ink3); border-color: var(--cbi-border2); background: transparent; }
.cbi-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; flex: none; }

/* Buttons ------------------------------------------------------------ */
.cbi-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex: none;
  padding: 4px 9px;
  border: 1px solid var(--cbi-border2);
  border-radius: var(--cbi-radius);
  background: var(--cbi-layer1);
  color: var(--cbi-ink);
  font-size: 12px;
  line-height: 18px;
  cursor: pointer;
  white-space: nowrap;
}
@media (hover: hover) { .cbi-btn:hover { background: var(--cbi-hover); } }
.cbi-btn:focus-visible { outline: 2px solid var(--cbi-brand); outline-offset: 1px; }
.cbi-btn[disabled] { opacity: 0.5; cursor: default; }
.cbi-btn-primary { background: var(--cbi-brand); border-color: var(--cbi-brand); color: var(--cbi-on-brand); }
@media (hover: hover) { .cbi-btn-primary:hover { background: var(--cbi-brand); filter: brightness(1.06); } }
.cbi-btn-ghost { background: transparent; border-color: transparent; color: var(--cbi-ink2); }
@media (hover: hover) { .cbi-btn-ghost:hover { background: var(--cbi-hover); color: var(--cbi-ink); } }
.cbi-btn-icon { padding: 4px 6px; }
.cbi-btn-sm { padding: 1px 6px; font-size: 11px; line-height: 16px; }
.cbi-btn-warn { color: var(--cbi-warn); border-color: var(--cbi-warn); }

/* Forms -------------------------------------------------------------- */
.cbi-form { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.cbi-form-row { display: flex; align-items: flex-end; gap: 6px; flex-wrap: wrap; min-width: 0; }
.cbi-field { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1 1 140px; }
.cbi-field-inline { flex: 0 1 auto; }
.cbi-label { font-size: 11px; color: var(--cbi-ink3); }
.cbi-input,
.cbi-select,
.cbi-textarea {
  width: 100%;
  min-width: 0;
  padding: 4px 7px;
  border: 1px solid var(--cbi-border2);
  border-radius: var(--cbi-radius);
  background: var(--cbi-layer1);
  color: var(--cbi-ink);
  font-size: 12px;
  line-height: 18px;
  outline: none;
}
.cbi-textarea { resize: vertical; min-height: 54px; font-family: var(--cbi-sans); }
.cbi-input:focus,
.cbi-select:focus,
.cbi-textarea:focus { border-color: var(--cbi-brand); box-shadow: 0 0 0 2px color-mix(in srgb, var(--cbi-brand) 22%, transparent); }
.cbi-input::placeholder,
.cbi-textarea::placeholder { color: var(--cbi-caption); }

/* Tables ------------------------------------------------------------- */
.cbi-table-block { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.cbi-table-wrap { overflow-x: auto; border: 1px solid var(--cbi-border); border-radius: var(--cbi-radius); min-width: 0; }
.cbi-table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 11.5px; }
.cbi-table th {
  padding: 4px 7px;
  border-bottom: 1px solid var(--cbi-border);
  background: var(--cbi-layer2);
  color: var(--cbi-ink3);
  font-weight: 500;
  font-size: 10.5px;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cbi-table td {
  padding: 4px 7px;
  border-top: 1px solid var(--cbi-border);
  color: var(--cbi-ink2);
  vertical-align: top;
  overflow-wrap: anywhere;
}
.cbi-table tr:first-child td { border-top: 0; }
@media (hover: hover) { .cbi-table tbody tr:hover td { background: var(--cbi-hover); } }
.cbi-col-num { text-align: right; font-variant-numeric: tabular-nums; }
.cbi-more {
  font-size: 11px;
  color: var(--cbi-ink3);
  padding: 1px 2px;
}
.cbi-muted { color: var(--cbi-caption); }
.cbi-mono { font-family: var(--cbi-mono); font-size: 11px; overflow-wrap: anywhere; }

/* Path citations ----------------------------------------------------- */
.cbi-pathref { display: inline; font-family: var(--cbi-mono); font-size: 11px; overflow-wrap: anywhere; }
.cbi-pathref:not([data-static="true"]) { cursor: copy; }
.cbi-pathref .cbi-path { color: var(--cbi-ink); }
.cbi-pathref .cbi-line { color: var(--cbi-brand); font-size: 10px; }
.cbi-pathref[data-static="true"] { cursor: default; }

/* Budget ------------------------------------------------------------- */
.cbi-budget {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
  padding: 5px 8px;
  border: 1px solid var(--cbi-border);
  border-radius: var(--cbi-radius);
  background: var(--cbi-layer2);
  font-size: 11px;
  color: var(--cbi-ink3);
}
.cbi-budget-label { color: var(--cbi-ink2); font-weight: 500; }
.cbi-budget-bar {
  position: relative;
  flex: 1 1 60px;
  min-width: 48px;
  height: 4px;
  border-radius: 2px;
  background: var(--cbi-border);
  overflow: hidden;
}
.cbi-budget-fill { position: absolute; top: 0; left: 0; bottom: 0; background: var(--cbi-brand); border-radius: 2px; }
.cbi-budget-fill[data-over="true"] { background: var(--cbi-warn); }

/* Excerpts ----------------------------------------------------------- */
.cbi-excerpt-list { display: flex; flex-direction: column; gap: 6px; }
.cbi-excerpt {
  border: 1px solid var(--cbi-border);
  border-radius: var(--cbi-radius);
  background: var(--cbi-layer1);
  padding: 6px 8px;
  min-width: 0;
}
.cbi-excerpt-head { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px; min-width: 0; }
.cbi-excerpt-symbol { color: var(--cbi-ink3); font-size: 10.5px; overflow-wrap: anywhere; }
.cbi-excerpt-reason { color: var(--cbi-ink3); font-size: 10.5px; font-style: italic; }
.cbi-code {
  margin: 5px 0 0;
  padding: 6px 8px;
  border-radius: var(--cbi-radius);
  background: var(--cbi-layer2);
  border: 1px solid var(--cbi-border);
  color: var(--cbi-ink2);
  font-family: var(--cbi-mono);
  font-size: 10.5px;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 260px;
  overflow: auto;
  tab-size: 2;
}

/* Small facts list --------------------------------------------------- */
.cbi-facts { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11.5px; color: var(--cbi-ink3); }
.cbi-fact { display: inline-flex; align-items: baseline; gap: 4px; min-width: 0; }
.cbi-fact-key { color: var(--cbi-ink3); }
.cbi-fact-value { color: var(--cbi-ink); font-family: var(--cbi-mono); font-size: 11px; overflow-wrap: anywhere; }

/* Export checklist --------------------------------------------------- */
.cbi-checklist { display: flex; flex-direction: column; gap: 3px; }
.cbi-check-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 5px;
  border-radius: var(--cbi-radius);
  min-width: 0;
}
@media (hover: hover) { .cbi-check-row:hover { background: var(--cbi-hover); } }
.cbi-check-name { flex: 1 1 auto; min-width: 0; font-family: var(--cbi-mono); font-size: 11px; color: var(--cbi-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cbi-check-size { flex: none; color: var(--cbi-ink3); font-size: 10.5px; font-variant-numeric: tabular-nums; }
.cbi-write-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }

/* Git panel ---------------------------------------------------------- */
.cbi-command {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px 8px;
  border: 1px dashed var(--cbi-border3);
  border-radius: var(--cbi-radius);
  background: var(--cbi-layer2);
  min-width: 0;
}
.cbi-command code {
  flex: 1 1 auto;
  min-width: 0;
  font-family: var(--cbi-mono);
  font-size: 10.5px;
  color: var(--cbi-ink2);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.cbi-changes { margin: 0; padding-left: 16px; font-family: var(--cbi-mono); font-size: 10.5px; color: var(--cbi-ink3); overflow-wrap: anywhere; }
.cbi-changes li { margin: 1px 0; }

/* States ------------------------------------------------------------- */
.cbi-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 22px 12px;
  color: var(--cbi-ink3);
  text-align: center;
  font-size: 12px;
}
.cbi-state-title { color: var(--cbi-ink2); font-weight: 500; }
.cbi-state-hint { font-size: 11px; color: var(--cbi-caption); max-width: 46ch; }
.cbi-spinner {
  width: 14px;
  height: 14px;
  flex: none;
  border-radius: 50%;
  border: 2px solid var(--cbi-border2);
  border-top-color: var(--cbi-brand);
  animation: cbi-spin 0.8s linear infinite;
}
@keyframes cbi-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .cbi-spinner { animation-duration: 2.4s; } }
.cbi-loading { display: flex; align-items: center; gap: 6px; padding: 14px 8px; color: var(--cbi-ink3); font-size: 12px; }
.cbi-error {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 8px 10px;
  border: 1px solid var(--cbi-danger);
  border-radius: var(--cbi-radius);
  background: color-mix(in srgb, var(--cbi-danger) 7%, transparent);
  color: var(--cbi-ink);
  font-size: 12px;
  min-width: 0;
}
.cbi-error-head { display: flex; align-items: center; gap: 5px; color: var(--cbi-danger); font-weight: 600; }
.cbi-error-message { color: var(--cbi-ink2); overflow-wrap: anywhere; }
.cbi-error-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cbi-toast {
  position: absolute;
  right: 10px;
  bottom: 10px;
  z-index: 5;
  padding: 4px 9px;
  border-radius: var(--cbi-radius);
  background: var(--dsw-alias-toast-bg, var(--cbi-layer1));
  color: var(--dsw-alias-toast-label, var(--cbi-ink));
  box-shadow: var(--dsw-shadow-lv2, 0 4px 14px rgba(0, 0, 0, 0.18));
  font-size: 11px;
}

/* Footer and guide entry --------------------------------------------- */
.cbi-foot {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 12px 7px;
  border-top: 1px solid var(--cbi-border);
  color: var(--cbi-caption);
  font-size: 10px;
  background: var(--cbi-layer1);
}
.cbi-root-main .cbi-foot { padding: 8px 0 12px; background: transparent; border-top-color: var(--cbi-border2); }
.cbi-foot-mono { font-family: var(--cbi-mono); font-size: 10px; }

.cbi-guide-entry {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 14px;
  width: 100%;
  height: auto;
  min-height: 68px;
  padding: 14px 20px;
  border: 1px solid var(--cbi-border3);
  border-radius: 20px;
  background: var(--cbi-layer1);
  color: var(--cbi-ink);
  font-family: var(--cbi-sans);
  font-size: 14px;
  line-height: normal;
  text-align: left;
  cursor: pointer;
  min-width: 0;
  overflow: visible;
  transition: background .15s ease, border-color .15s ease, color .15s ease;
}
@media (hover: hover) { .cbi-guide-entry:hover { background: var(--cbi-hover); border-color: var(--cbi-border2); } }
.cbi-guide-entry:focus-visible { outline: 2px solid var(--cbi-brand); outline-offset: 2px; }
.cbi-guide-icon { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; flex: none; color: var(--cbi-brand); }
.cbi-guide-text { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1 1 auto; }
.cbi-guide-title { display: block; font-size: 14px; font-weight: 400; line-height: 19.6px; color: var(--cbi-ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cbi-guide-desc { display: block; font-size: 11px; line-height: 15.4px; color: var(--cbi-ink3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* Scrollbars --------------------------------------------------------- */
.cbi-root ::-webkit-scrollbar { width: 8px; height: 8px; }
.cbi-root ::-webkit-scrollbar-thumb { background: var(--cbi-border2); border-radius: 4px; }
.cbi-root ::-webkit-scrollbar-track { background: transparent; }

.cbi-graph-toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; justify-content:space-between; margin:8px 0; }
.cbi-graph-nav, .cbi-graph-tools, .cbi-graph-zoom { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.cbi-graph-crumb { border:0; background:transparent; color:var(--cbi-ink2); font:inherit; font-size:12px; padding:3px 7px; border-radius:999px; cursor:pointer; }
.cbi-graph-crumb:hover:not(:disabled) { background:var(--cbi-hover); color:var(--cbi-ink); }
.cbi-graph-crumb:disabled { color:var(--cbi-ink); font-weight:600; cursor:default; }
.cbi-graph-crumb + .cbi-graph-crumb::before { content:"/"; color:var(--cbi-caption); margin-right:6px; }
.cbi-graph-select { display:inline-flex; align-items:center; gap:5px; font-size:12px; color:var(--cbi-ink2); }
.cbi-graph-select select { font:inherit; font-size:12px; background:var(--cbi-layer1); color:var(--cbi-ink); border:1px solid var(--cbi-border2); border-radius:7px; padding:4px 6px; }
.cbi-graph-search { width:170px; font:inherit; font-size:12px; background:var(--cbi-layer1); color:var(--cbi-ink); border:1px solid var(--cbi-border2); border-radius:7px; padding:5px 8px; }
.cbi-graph-search:focus { outline:2px solid var(--cbi-brand); outline-offset:1px; }
.cbi-chip { font:inherit; font-size:12px; background:var(--cbi-layer1); color:var(--cbi-ink2); border:1px solid var(--cbi-border2); border-radius:999px; padding:4px 9px; cursor:pointer; }
.cbi-chip[aria-pressed="true"] { border-color:var(--cbi-brand); color:var(--cbi-brand); background:var(--cbi-hover); }
.cbi-chip:hover { background:var(--cbi-hover); }
.cbi-graph-legend { display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin:2px 0 8px; color:var(--cbi-ink3); font-size:11px; }
.cbi-graph-legend-item { display:inline-flex; align-items:center; gap:5px; }
.cbi-graph-legend-sep { width:1px; height:12px; background:var(--cbi-border2); }
.cbi-graph-dot { width:8px; height:8px; border-radius:2px; display:inline-block; }
.cbi-graph-dot--dir { background:var(--cbi-brand); }
.cbi-graph-dot--file { background:var(--cbi-ink2); }
.cbi-graph-dot--symbol { background:var(--cbi-ok); border-radius:50%; }
.cbi-graph-dot--unresolved { background:transparent; border:1px dashed var(--cbi-ink3); }
.cbi-graph-line { width:16px; height:0; border-top:2px solid var(--cbi-ink3); display:inline-block; }
.cbi-graph-line--resolved { border-top-color:var(--cbi-brand); border-top-style:solid; }
.cbi-graph-line--heuristic { border-top-color:var(--cbi-warn); border-top-style:dashed; }
.cbi-graph-line--unresolved { border-top-color:var(--cbi-ink3); border-top-style:dotted; }
.cbi-graph-stage { overflow:auto; max-height:58vh; border:1px solid var(--cbi-border2); border-radius:10px;
  background-image:radial-gradient(circle at 1px 1px, var(--cbi-border) 1px, transparent 0);
  background-size:18px 18px; background-color:var(--cbi-bg); }
.cbi-graph-stage:focus-visible { outline:2px solid var(--cbi-brand); outline-offset:2px; }
.cbi-graph-canvas { display:block; min-width:100%; }
.cbi-graph-arrow--resolved { fill:var(--cbi-brand); }
.cbi-graph-arrow--heuristic { fill:var(--cbi-warn); }
.cbi-graph-arrow--unresolved { fill:var(--cbi-ink3); }
.cbi-graph-edges { pointer-events:auto; }
.cbi-graph-edge { cursor:pointer; }
.cbi-graph-edge-hit { fill:none; stroke:transparent; stroke-width:14; }
.cbi-graph-edge-line { fill:none; }
.cbi-graph-edge--resolved .cbi-graph-edge-line { stroke:var(--cbi-brand); }
.cbi-graph-edge--heuristic .cbi-graph-edge-line { stroke:var(--cbi-warn); stroke-dasharray:5 4; }
.cbi-graph-edge--unresolved .cbi-graph-edge-line { stroke:var(--cbi-ink3); stroke-dasharray:2 4; }
.cbi-graph-edge--selected .cbi-graph-edge-line { stroke-width:3.2; filter:drop-shadow(0 0 2px var(--cbi-brand)); }
.cbi-graph-edge--dim { opacity:.16; }
.cbi-graph-edge-label { fill:var(--cbi-ink2); font-size:10px; text-anchor:middle; paint-order:stroke; stroke:var(--cbi-bg); stroke-width:3px; pointer-events:none; }
.cbi-graph-node { cursor:pointer; outline:none; }
.cbi-graph-node-card { fill:var(--cbi-layer1); stroke:var(--cbi-border2); stroke-width:1.2; filter:drop-shadow(0 1px 1px rgba(0,0,0,.05)); }
.cbi-graph-node-accent { fill:var(--cbi-ink2); }
.cbi-graph-node--dir .cbi-graph-node-accent { fill:var(--cbi-brand); }
.cbi-graph-node--file .cbi-graph-node-accent { fill:var(--cbi-ink2); }
.cbi-graph-node--symbol .cbi-graph-node-accent { fill:var(--cbi-ok); }
.cbi-graph-node--unresolved .cbi-graph-node-accent { fill:var(--cbi-ink3); }
.cbi-graph-node-glyph { font-size:13px; font-weight:700; fill:var(--cbi-ink3); }
.cbi-graph-node-label { font-size:12px; font-weight:600; fill:var(--cbi-ink); }
.cbi-graph-node-meta { font-size:10px; fill:var(--cbi-ink3); }
.cbi-graph-node--focus .cbi-graph-node-card { fill:var(--cbi-hover); stroke:var(--cbi-brand); stroke-width:2; }
.cbi-graph-node--selected .cbi-graph-node-card { stroke:var(--cbi-brand); stroke-width:2.6; }
.cbi-graph-node--related .cbi-graph-node-card { stroke:var(--cbi-brand); stroke-width:1.8; }
.cbi-graph-node--dim { opacity:.2; }
.cbi-graph-node:hover .cbi-graph-node-card, .cbi-graph-node:focus-visible .cbi-graph-node-card { stroke:var(--cbi-brand); stroke-width:2; }
.cbi-graph-status { display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin:8px 0; color:var(--cbi-ink3); font-size:11px; }
.cbi-graph-match { color:var(--cbi-brand); font-weight:600; }
.cbi-graph-pager { display:inline-flex; gap:6px; align-items:center; margin-left:auto; }
.cbi-graph-detail-grid { display:grid; grid-template-columns:minmax(0,1fr); gap:10px; }
.cbi-graph-inspector-head { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:6px; }
.cbi-graph-inspector-head strong { font-size:13px; word-break:break-all; }
.cbi-graph-actions { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0; }
.cbi-graph-relations { border-top:1px solid var(--cbi-border); margin-top:8px; padding-top:8px; }
.cbi-graph-relations-head { font-size:11px; color:var(--cbi-ink3); margin-bottom:4px; }
.cbi-graph-rel-row { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:8px; width:100%; text-align:left;
  background:transparent; border:1px solid transparent; border-radius:7px; padding:5px 6px; cursor:pointer; font:inherit; font-size:11px; color:var(--cbi-ink2); }
.cbi-graph-rel-row:hover { background:var(--cbi-hover); border-color:var(--cbi-border2); }
.cbi-graph-rel-type { font-weight:600; color:var(--cbi-ink); }
.cbi-graph-rel-target { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.cbi-graph-rel-meta { color:var(--cbi-caption); white-space:nowrap; }
.cbi-graph-hint { font-size:12px; margin:2px 0 8px; }
.cbi-graph-edge-list { max-height:240px; overflow:auto; }
.cbi-graph-edge-list button { white-space:normal; text-align:left; }
.cbi-graph-evidence { margin-top:2px; }
.cbi-graph-source-wrap { border:1px solid var(--cbi-border); border-radius:8px; overflow:hidden; }
.cbi-graph-source-head { padding:5px 8px; border-bottom:1px solid var(--cbi-border); background:var(--cbi-layer2); font-size:11px; }
.cbi-graph-source { overflow:auto; max-height:320px; white-space:pre; margin:0; font-family:var(--cbi-mono); font-size:11px; line-height:1.5; padding:8px; background:var(--cbi-layer1); }
.cbi-graph-source span { display:block; }
.cbi-graph-line-no { color:var(--cbi-caption); user-select:none; }
.cbi-graph-highlight { background:var(--cbi-hover); font-weight:700; }
@media (max-width: 620px) { .cbi-graph-search { width:130px; } .cbi-graph-toolbar { align-items:flex-start; } .cbi-graph-stage { max-height:52vh; } }
`

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

/**
 * dsh-codebase-intelligence — 04-panel
 *
 * The one Panel component shared by the right-sidebar pane and the full-page
 * fallback: header facts, seven views (概览/地图/项目图谱/搜索/依赖/上下文/生成), bounded
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
        if (!confirmWrite(t("export.writeConfirm", { dir: outDir, total: fmtInt(counts.total) }))) return
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
          git.command
            ? h(
                "div",
                { className: "cbi-command" },
                h(Glyph, { name: "file", size: 13 }),
                h("code", null, git.command),
                h(CopyButton, { t: t, text: git.command, label: t("common.copyCommand") }),
              )
            : null,
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
              { key: "count", label: t("export.previewFacts"), value: t("export.fileCount", { n: fmtInt(counts.total - counts.missing), total: fmtInt(counts.total) }) },
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

    let graphInstance = 0

    const GRAPH_RELATIONS = ["imports", "calls", "inherits", "implements", "references", "contains", "defines"]
    const GRAPH_EDGE_TONES = ["resolved", "heuristic", "unresolved"]
    const GRAPH_EDGE_KINDS = ["parser", "resolver", "heuristic"]

    function graphKindLabel(t, kind) {
      const key = "graph.kind." + kind
      const label = t(key)
      return label === key ? kind : label
    }

    function graphRelationLabel(t, kind) {
      const value = toText(kind) || "other"
      const key = "graph.relation." + value
      const label = t(key)
      return label === key ? value : label
    }

    function graphStatusLabel(t, status) {
      const value = toText(status) || "unresolved"
      const key = "graph.status." + value
      const label = t(key)
      return label === key ? value : label
    }

    function graphEvidenceLabel(t, evidence) {
      const value = toText(evidence) || "heuristic"
      const key = "graph.evidence." + value
      const label = t(key)
      return label === key ? value : label
    }

    function graphEdgeToneLabel(t, tone) {
      const key = "graph.edge." + toText(tone)
      const label = t(key)
      return label === key ? toText(tone) : label
    }

    function graphSourceLabel(t, source) {
      const value = toText(source)
      const key = "graph.source." + value
      const label = t(key)
      return label === key ? value : label
    }

    function graphNodeGlyph(node) {
      const kind = graphNodeTone(node)
      return kind === "dir" ? "▸" : kind === "file" ? "▤" : kind === "symbol" ? "ƒ" : "?"
    }

    function graphNodeMeta(node, t) {
      const kind = graphNodeTone(node)
      if (kind === "symbol") {
        return clampText((node.symbolKind || graphKindLabel(t, "symbol")) + (node.line ? " · " + node.line : ""), 28)
      }
      if (kind === "unresolved") return graphKindLabel(t, "unresolved")
      return clampText(node.path || graphKindLabel(t, kind), 28)
    }

    function graphEdgeText(t, edge, labels) {
      const from = labels[edge.from] || edge.from
      const to = labels[edge.to] || edge.to
      return from + " → " + to + " · " + graphRelationLabel(t, edge.type) + " · "
        + graphStatusLabel(t, edge.status) + " · " + graphEvidenceLabel(t, edge.evidence) + " ×" + edge.count
    }

    function GraphSource(props) {
      const t = props.t
      const span = props.span
      const request = useLoad(function () {
        return apiGet("/api/graph", withSession(props.sessionId, {
          source: span.path, line: span.startLine, fingerprint: props.fingerprint,
        }))
      }, [props.sessionId, span.path, span.startLine, props.fingerprint])
      if (request.status === "loading") return h(Loading, { t: t })
      if (request.status === "error") return h(ErrorBox, { t: t, error: request.error, onRetry: request.reload })
      const result = request.data
      return h("div", { className: "cbi-graph-source-wrap" },
        h("div", { className: "cbi-graph-source-head" }, h(PathRef, { path: result.path, line: result.line })),
        h("pre", { className: "cbi-graph-source", tabIndex: 0, "aria-label": result.path },
          safeArray(result.lines).map(function (line, index) {
            const number = result.startLine + index
            return h("span", { key: number, className: number === result.line ? "cbi-graph-highlight" : "" },
              h("span", { className: "cbi-graph-line-no" }, String(number).padStart(4, " ")),
              "  " + line + "\n")
          }),
        ),
      )
    }

    function GraphCanvas(props) {
      const t = props.t
      const markerId = useMemo(function () { graphInstance += 1; return "cbi-arrow-" + graphInstance }, [])
      const viewport = useRef(null)
      const layout = props.layout
      const positions = layout.positions
      const nodes = layout.nodes
      const edges = props.edges
      const selectedNodeId = props.selected && props.selected.type === "node" ? props.selected.node.id : ""
      const selectedEdgeKey = props.selected && props.selected.type === "edge" ? props.selected.edge.key : ""
      const hasQuery = toText(props.query).trim().length > 0
      const matches = props.matches || Object.create(null)
      const labels = Object.create(null)
      nodes.forEach(function (node) { labels[node.id] = node.label })
      const related = Object.create(null)
      if (selectedNodeId) {
        edges.forEach(function (edge) {
          if (edge.from === selectedNodeId) related[edge.to] = true
          if (edge.to === selectedNodeId) related[edge.from] = true
        })
      }
      useEffect(function () {
        if (viewport.current && props.scroll) {
          viewport.current.scrollLeft = props.scroll.left
          viewport.current.scrollTop = props.scroll.top
        }
      }, [])
      useEffect(function () {
        if (viewport.current) {
          viewport.current.scrollLeft = 0
          viewport.current.scrollTop = 0
        }
      }, [props.resetToken])
      const clearOnBackground = function (event) {
        if (event.target === event.currentTarget && typeof props.onClear === "function") props.onClear()
      }
      return h("div", {
        className: "cbi-graph-stage", ref: viewport, tabIndex: 0,
        role: "region", "aria-label": t("graph.canvasLabel"),
        onScroll: function (event) {
          if (typeof props.onScroll === "function") {
            props.onScroll({ left: event.currentTarget.scrollLeft, top: event.currentTarget.scrollTop })
          }
        },
        onClick: clearOnBackground,
      },
        h("svg", {
          className: "cbi-graph-canvas",
          width: layout.width * props.zoom,
          height: layout.height * props.zoom,
          viewBox: "0 0 " + layout.width + " " + layout.height,
          role: "group",
          "aria-label": t("graph.canvasLabel"),
          onClick: clearOnBackground,
        },
          h("defs", null, GRAPH_EDGE_TONES.map(function (tone) {
            return h("marker", {
              key: tone, id: markerId + tone, viewBox: "0 0 10 10",
              refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto",
            }, h("path", { d: "M 0 0 L 10 5 L 0 10 z", className: "cbi-graph-arrow cbi-graph-arrow--" + tone }))
          })),
          h("g", { className: "cbi-graph-edges" }, edges.map(function (edge) {
            const from = positions[edge.from]
            const to = positions[edge.to]
            if (!from || !to) return null
            const geometry = graphEdgeGeometry(from, to)
            const tone = graphEdgeTone(edge)
            const selected = selectedEdgeKey === edge.key
            const dim = (selectedNodeId && edge.from !== selectedNodeId && edge.to !== selectedNodeId)
              || (selectedEdgeKey && !selected)
              || (hasQuery && !matches[edge.from] && !matches[edge.to])
            const classes = ["cbi-graph-edge", "cbi-graph-edge--" + tone]
            if (selected) classes.push("cbi-graph-edge--selected")
            if (dim) classes.push("cbi-graph-edge--dim")
            const aria = graphEdgeText(t, edge, labels)
            return h("g", {
              key: edge.key, className: classes.join(" "), role: "button", tabIndex: 0, "aria-label": aria,
              onClick: function (event) { event.stopPropagation(); props.onEdge(edge) },
              onKeyDown: function (event) {
                if (event.key === "Enter" || event.key === " ") { event.preventDefault(); props.onEdge(edge) }
              },
            },
              h("title", null, aria),
              h("path", { className: "cbi-graph-edge-hit", d: geometry.path }),
              h("path", {
                className: "cbi-graph-edge-line", d: geometry.path,
                "marker-end": "url(#" + markerId + tone + ")",
                "stroke-width": Math.min(3.4, 1.1 + Math.log2(edge.count)),
              }),
              selected ? h("text", { className: "cbi-graph-edge-label", x: geometry.labelX, y: geometry.labelY - 6 },
                graphRelationLabel(t, edge.type) + " ×" + edge.count) : null,
            )
          })),
          h("g", { className: "cbi-graph-nodes" }, nodes.map(function (node) {
            const pos = positions[node.id]
            if (!pos) return null
            const kind = graphNodeTone(node)
            const selected = selectedNodeId === node.id
            const dim = (selectedEdgeKey && !selected)
              || (selectedNodeId && !selected && !related[node.id])
              || (hasQuery && !matches[node.id])
              || (!props.showUnresolved && kind === "unresolved")
            const classes = ["cbi-graph-node", "cbi-graph-node--" + kind]
            if (node.side === "focus") classes.push("cbi-graph-node--focus")
            if (selected) classes.push("cbi-graph-node--selected")
            if (related[node.id]) classes.push("cbi-graph-node--related")
            if (dim) classes.push("cbi-graph-node--dim")
            const enter = function () {
              if (node.kind !== "unresolved" && node.side !== "focus") props.onEnter(node)
            }
            return h("g", {
              key: node.id, className: classes.join(" "), transform: "translate(" + pos.x + "," + pos.y + ")",
              role: "button", tabIndex: 0, "aria-label": node.label, "aria-pressed": selected ? "true" : "false",
              onClick: function (event) { event.stopPropagation(); props.onSelect(node) },
              onDoubleClick: function (event) { event.stopPropagation(); enter() },
              onKeyDown: function (event) {
                if (event.key === "Enter" || event.key === " ") { event.preventDefault(); props.onSelect(node) }
              },
            },
              h("title", null, node.path ? node.path + (node.line ? ":" + node.line : "") : node.label),
              h("rect", { className: "cbi-graph-node-card", width: GRAPH_NODE_WIDTH, height: GRAPH_NODE_HEIGHT, rx: 10 }),
              h("rect", { className: "cbi-graph-node-accent", width: 4, height: GRAPH_NODE_HEIGHT, rx: 2 }),
              h("text", { className: "cbi-graph-node-glyph", x: 18, y: 32 }, graphNodeGlyph(node)),
              h("text", { className: "cbi-graph-node-label", x: 38, y: 24 }, clampText(node.label, 23)),
              h("text", { className: "cbi-graph-node-meta", x: 38, y: 42 }, graphNodeMeta(node, t)),
            )
          })),
        ),
      )
    }

    function GraphView(props) {
      const t = props.t
      const [trail, setTrail] = useState([{ id: "", offset: 0, relation: "" }])
      const [zoom, setZoom] = useState(1)
      const [selection, select] = useState(null)
      const [query, setQuery] = useState("")
      const [showUnresolved, setShowUnresolved] = useState(true)
      const [refreshing, setRefreshing] = useState(false)
      const [refreshError, setRefreshError] = useState(null)
      const [resetToken, setResetToken] = useState(0)
      const scrollPositions = useRef(new Map())
      const position = trail[trail.length - 1]
      const focus = position.id
      const offset = position.offset
      const relation = position.relation
      const viewKey = JSON.stringify([focus, offset, relation])
      const clearSelection = function () { select(null) }
      const open = function (node, nextOffset) {
        if (node.id === focus && (nextOffset || 0) === offset) return
        select(null)
        setQuery("")
        setTrail(function (old) {
          return old.slice(-63).concat({ id: node.id, offset: nextOffset || 0, relation: node.id === focus ? relation : "" })
        })
      }
      const back = function () {
        select(null)
        setTrail(function (old) { return old.length > 1 ? old.slice(0, -1) : old })
      }
      const request = useLoad(function () {
        return apiGet("/api/graph", withSession(props.sessionId, { focus: focus, offset: offset, relation: relation }))
      }, [props.sessionId, props.refreshToken, focus, offset, relation])
      const refresh = async function () {
        setRefreshing(true)
        setRefreshError(null)
        try {
          await apiPost("/api/graph", refreshBody(props.sessionId))
          select(null)
          setQuery("")
          setResetToken(function (value) { return value + 1 })
          scrollPositions.current.clear()
          setTrail([{ id: "", offset: 0, relation: "" }])
          request.reload()
        } catch (error) {
          setRefreshError({ message: messageOf(error), code: errorCodeOf(error) })
        } finally {
          setRefreshing(false)
        }
      }
      const graph = request.data && request.data.focus === focus && request.data.offset === offset && request.data.relation === relation ? request.data : null
      const nodes = useMemo(function () { return graphNodeRows(graph && graph.nodes) }, [graph])
      const edges = useMemo(function () { return graphEdgeRows(graph && graph.edges) }, [graph])
      const matches = useMemo(function () { return graphMatchMap(nodes, query) }, [nodes, query])
      const visibleEdges = useMemo(function () {
        return graphVisibleEdges(edges, { relation: relation, showUnresolved: showUnresolved, query: query, matches: matches })
      }, [edges, relation, showUnresolved, query, matches])
      const layout = useMemo(function () { return graphLayout(nodes, edges) }, [nodes, edges])
      const degrees = useMemo(function () { return graphDegrees(nodes, edges) }, [nodes, edges])
      const labels = useMemo(function () {
        const value = Object.create(null)
        nodes.forEach(function (node) { value[node.id] = node.label })
        return value
      }, [nodes])
      const selectedNode = selection && selection.type === "node" ? selection.node : null
      const selectedEdge = selection && selection.type === "edge" && selection.fingerprint === graph?.fingerprint ? selection.edge : null
      const selectedSpan = selectedEdge ? selection.span : null
      const currentSource = selection && selection.type === "source" && selection.fingerprint === graph?.fingerprint
        ? { path: selection.path, startLine: selection.line, line: selection.line }
        : selectedSpan
          ? { path: selectedSpan.path, startLine: selectedSpan.startLine, line: selectedSpan.startLine }
          : null
      useEffect(function () {
        if (!selection || selection.type !== "node") return
        if (!nodes.some(function (node) { return node.id === selection.node.id })) select(null)
      }, [nodes, selection])
      const chooseNode = function (node) { select({ type: "node", node: node }) }
      const chooseEdge = function (edge) {
        select({ type: "edge", edge: edge, span: safeArray(edge.sites)[0] || null, fingerprint: graph.fingerprint })
      }
      const enterNode = function (node) {
        if (node.kind === "unresolved" || node.side === "focus") return
        open({ id: node.id })
      }
      const viewNodeSource = function (node) {
        if (!node.path) return
        select({ type: "source", path: node.path, line: node.line || 1, fingerprint: graph.fingerprint })
      }
      const matchCount = nodes.filter(function (node) { return matches[node.id] }).length
      const rootButton = function (label, onClick, disabled) {
        return h(Btn, { size: "sm", tone: "ghost", onClick: onClick, disabled: disabled }, label)
      }
      const crumbs = safeArray(graph && graph.breadcrumbs)
      const relationSelect = focus && !focus.startsWith("dir:")
        ? h("label", { className: "cbi-graph-select" }, h("span", null, t("graph.filter")),
          h("select", { value: relation, onChange: function (event) {
            const value = event.currentTarget.value
            select(null)
            setTrail(function (old) { return old.slice(0, -1).concat({ id: focus, offset: 0, relation: value }) })
          } }, [""].concat(GRAPH_RELATIONS).map(function (kind) {
            return h("option", { key: kind, value: kind }, kind ? graphRelationLabel(t, kind) : t("graph.all"))
          })))
        : null
      const selectedFacts = selectedNode
        ? [
            { key: "kind", label: t("graph.nodeKind"), value: graphKindLabel(t, selectedNode.kind) },
            { key: "path", label: t("graph.nodePath"), value: selectedNode.path || "—", raw: selectedNode.path || undefined },
            { key: "line", label: t("graph.nodeLine"), value: selectedNode.line ? String(selectedNode.line) : "—" },
            { key: "degree", label: t("graph.nodeDegree"), value: (degrees[selectedNode.id]?.in || 0) + " ← · → " + (degrees[selectedNode.id]?.out || 0) },
          ]
        : []
      const touching = selectedNode
        ? edges.filter(function (edge) { return edge.from === selectedNode.id || edge.to === selectedNode.id })
        : []
      const relationRow = function (edge) {
        const otherId = edge.from === selectedNode.id ? edge.to : edge.from
        const other = labels[otherId] || otherId
        return h("button", {
          type: "button", key: edge.key, className: "cbi-graph-rel-row",
          onClick: function () { chooseEdge(edge) },
        },
          h("span", { className: "cbi-graph-rel-type" }, graphRelationLabel(t, edge.type)),
          h("span", { className: "cbi-graph-rel-target" }, (edge.from === selectedNode.id ? "→ " : "← ") + other),
          h("span", { className: "cbi-graph-rel-meta" }, graphStatusLabel(t, edge.status) + " ×" + edge.count),
        )
      }
      return h("section", null,
        h(ViewLead, { title: t("view.graph"), subtitle: t("graph.help") }),
        h("div", { className: "cbi-graph-toolbar" },
          h("div", { className: "cbi-graph-nav" },
            rootButton(t("graph.back"), back, trail.length < 2),
            rootButton(t("graph.root"), function () { open({ id: "" }) }, !focus && offset === 0),
            crumbs.map(function (crumb) {
              return h("button", {
                type: "button", key: crumb.id, className: "cbi-graph-crumb",
                disabled: crumb.id === focus && offset === 0,
                onClick: function () { open(crumb) },
              }, clampText(crumb.label, 20))
            }),
          ),
          h("div", { className: "cbi-graph-tools" },
            h(Btn, { size: "sm", glyph: "refresh", onClick: refresh, disabled: refreshing },
              refreshing ? t("graph.refreshing") : t("graph.refresh")),
            relationSelect,
            h("input", {
              type: "search", className: "cbi-graph-search", value: query,
              placeholder: t("graph.searchPlaceholder"), "aria-label": t("graph.searchPlaceholder"),
              onChange: function (event) { setQuery(event.currentTarget.value) },
            }),
            query ? h("button", { type: "button", className: "cbi-chip", onClick: function () { setQuery("") } }, t("graph.clearSearch")) : null,
            h("button", {
              type: "button", className: "cbi-chip", "aria-pressed": showUnresolved ? "true" : "false",
              onClick: function () { setShowUnresolved(function (value) { return !value }) },
            }, t(showUnresolved ? "graph.hideUnresolved" : "graph.showUnresolved")),
            h("div", { className: "cbi-graph-zoom" },
              h(Btn, { size: "sm", tone: "ghost", onClick: function () { setZoom(Math.max(0.5, zoom - 0.25)) }, disabled: zoom <= 0.5 }, "−"),
              h(Btn, { size: "sm", tone: "ghost", onClick: function () { setZoom(1); setResetToken(function (value) { return value + 1 }) } }, t("graph.fit")),
              h(Btn, { size: "sm", tone: "ghost", onClick: function () { setZoom(Math.min(2, zoom + 0.25)) }, disabled: zoom >= 2 }, "+"),
            ),
          ),
        ),
        h("div", { className: "cbi-graph-legend" },
          ["dir", "file", "symbol", "unresolved"].map(function (kind) {
            return h("span", { key: kind, className: "cbi-graph-legend-item" },
              h("i", { className: "cbi-graph-dot cbi-graph-dot--" + kind }), graphKindLabel(t, kind))
          }),
          h("span", { className: "cbi-graph-legend-sep" }),
          GRAPH_EDGE_TONES.map(function (tone) {
            return h("span", { key: tone, className: "cbi-graph-legend-item" },
              h("i", { className: "cbi-graph-line cbi-graph-line--" + tone }),
              graphEdgeToneLabel(t, tone))
          }),
        ),
        refreshError ? h(ErrorBox, { t: t, error: refreshError, onRetry: refresh }) : null,
        request.status === "error" ? h(ErrorBox, { t: t, error: request.error, onRetry: request.reload })
          : !graph ? h(Loading, { t: t })
          : nodes.length === 0 ? h(EmptyState, { title: t("graph.empty"), hint: t("graph.emptyHint") })
          : h(GraphCanvas, {
              key: viewKey, t: t, layout: layout, edges: visibleEdges, zoom: zoom, selected: selection,
              query: query, matches: matches, resetToken: resetToken,
              scroll: scrollPositions.current.get(viewKey), onScroll: function (scroll) {
                if (scrollPositions.current.size >= 64 && !scrollPositions.current.has(viewKey)) {
                  scrollPositions.current.delete(scrollPositions.current.keys().next().value)
                }
                scrollPositions.current.set(viewKey, scroll)
              },
              onSelect: chooseNode, onEnter: enterNode, onEdge: chooseEdge, onClear: clearSelection,
              showUnresolved: showUnresolved,
            }),
        graph ? h("div", { className: "cbi-graph-status" },
          h("span", null, t("graph.stats", {
            shown: fmtInt(nodes.length), total: fmtInt(graph.totalNodes),
            edges: fmtInt(visibleEdges.length), hidden: fmtInt(graph.omittedEdges),
          })),
          h("span", null, graphSourceLabel(t, graph.snapshotSource)),
          query ? h("span", { className: "cbi-graph-match" }, t("graph.searchCount", { n: fmtInt(matchCount), total: fmtInt(nodes.length) })) : null,
          h("span", { className: "cbi-graph-pager" },
            offset > 0 ? rootButton(t("graph.previous"), function () { open({ id: focus }, Math.max(0, offset - (focus.startsWith("sym:") ? 79 : 80))) }) : null,
            graph.nextOffset !== null ? rootButton(t("graph.next"), function () { open({ id: focus }, graph.nextOffset) }) : null,
          ),
        ) : null,
        graph ? h("div", { className: "cbi-graph-detail-grid" },
          selectedNode ? h(Section, {
            title: t("graph.inspector"),
            actions: h(Btn, { size: "sm", tone: "ghost", onClick: clearSelection }, t("graph.clearSelection")),
          },
            h("div", { className: "cbi-graph-inspector" },
              h("div", { className: "cbi-graph-inspector-head" },
                h("strong", null, selectedNode.label),
                h(Badge, { tone: "muted" }, graphKindLabel(t, selectedNode.kind)),
                selectedNode.side === "focus" ? h(Badge, { tone: "brand" }, t("graph.focusBadge")) : null,
              ),
              h(Facts, { facts: selectedFacts }),
              h("div", { className: "cbi-graph-actions" },
                selectedNode.kind !== "unresolved" && selectedNode.side !== "focus"
                  ? h(Btn, { size: "sm", tone: "primary", onClick: function () { enterNode(selectedNode) } }, t("graph.enter"))
                  : null,
                selectedNode.path && selectedNode.kind !== "dir" && selectedNode.kind !== "unresolved"
                  ? h(Btn, { size: "sm", glyph: "file", onClick: function () { viewNodeSource(selectedNode) } }, t("graph.viewSource"))
                  : null,
              ),
              touching.length ? h("div", { className: "cbi-graph-relations" },
                h("div", { className: "cbi-graph-relations-head" }, t("graph.relations"), " ", h("span", { className: "cbi-muted" }, fmtInt(touching.length))),
                touching.map(relationRow),
              ) : h("p", { className: "cbi-muted" }, t("graph.noRelations")),
            ),
          ) : null,
          selectedEdge ? h(Section, {
            title: t("graph.evidence"),
            actions: h(Btn, { size: "sm", tone: "ghost", onClick: clearSelection }, t("graph.clearSelection")),
          },
            h("div", { className: "cbi-graph-evidence" },
              h("strong", null, graphEdgeText(t, selectedEdge, labels)),
              h("div", { className: "cbi-graph-actions" },
                safeArray(selectedEdge.sites).map(function (span) {
                  return h(Btn, {
                    key: span.path + ":" + span.startLine, size: "sm", glyph: "file",
                    onClick: function () { select({ type: "edge", edge: selectedEdge, span: span, fingerprint: graph.fingerprint }) },
                    disabled: selectedSpan && selectedSpan.path === span.path && selectedSpan.startLine === span.startLine,
                  }, span.path + ":" + span.startLine)
                }),
              ),
              currentSource ? h(GraphSource, {
                key: currentSource.path + ":" + currentSource.startLine + ":" + graph.fingerprint,
                t: t, sessionId: props.sessionId,
                span: { path: currentSource.path, startLine: currentSource.startLine },
                fingerprint: graph.fingerprint,
              }) : h("p", { className: "cbi-muted" }, t("graph.noSource")),
            ),
          ) : null,
          selection && selection.type === "source" ? h(Section, {
            title: t("graph.sourceExcerpt"),
            actions: h(Btn, { size: "sm", tone: "ghost", onClick: clearSelection }, t("graph.clearSelection")),
          },
            h(GraphSource, {
              key: selection.path + ":" + selection.line + ":" + selection.fingerprint,
              t: t, sessionId: props.sessionId,
              span: { path: selection.path, startLine: selection.line },
              fingerprint: selection.fingerprint,
            }),
          ) : null,
          !selection ? h("p", { className: "cbi-muted cbi-graph-hint" }, t("graph.selectHint")) : null,
        ) : null,
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
        case "graph":
          return h(GraphView, Object.assign({ key: p.sessionId }, shared))
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

    /** Mount the namespaced stylesheet once in document.head so the Start-guide
     * card (rendered outside the panel root) is styled before the panel opens. */
    function ensureGlobalStyles() {
      if (typeof document === "undefined" || !document.head) return
      try {
        let node = document.getElementById("dsh-codebase-intelligence-styles")
        if (!node) {
          node = document.createElement("style")
          node.id = "dsh-codebase-intelligence-styles"
          node.setAttribute("data-dsh-codebase-intelligence", "styles")
          document.head.appendChild(node)
        }
        if (node.textContent !== STYLES) node.textContent = STYLES
      } catch (error) {
        /* style injection is best effort; the panel still has its inline sheet */
      }
    }

    /** Guide/Start card that opens the tab; `open` is injected by the host plugin.
     * Rendered by DSH as a row in the right-sidebar Start list, so it mirrors the
     * host row geometry instead of looking like a separate embedded card. */
    function GuideEntryCard(props) {
      const p = props || {}
      const t = typeof p.t === "function" ? p.t : makeT("zh")
      const title = typeof p.title === "string" && p.title.length > 0 ? p.title : t("guide.open")
      const description =
        typeof p.description === "string" && p.description.length > 0 ? p.description : t("guide.description")
      const open = typeof p.open === "function" ? p.open : null
      ensureGlobalStyles()
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
        h("span", { className: "cbi-guide-icon" }, h(PanelMark, { size: 26 })),
        h(
          "span",
          { className: "cbi-guide-text" },
          h("span", { className: "cbi-guide-title" }, title),
          h("span", { className: "cbi-guide-desc" }, description),
        ),
      )
    }

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
