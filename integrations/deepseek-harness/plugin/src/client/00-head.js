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
