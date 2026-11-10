# Design Principles

1. **Evidence before assertion** — attach source locations and extraction provenance to structural claims.
2. **Facts, inferences, and summaries are different** — represent them separately.
3. **Budget is a first-class input** — context selection must explain what was included and excluded.
4. **Local-first and private by default** — no implicit upload or telemetry containing source content.
5. **Incremental but correct** — cache only when invalidation can be reasoned about; otherwise rebuild.
6. **Language adapters, shared model** — avoid language-specific assumptions leaking into the core.
7. **Composable outputs** — JSON for machines, Markdown for people, MCP for agents.
8. **Graceful degradation** — unsupported syntax should be reported, not silently misrepresented.
9. **Small core** — defer databases, services, and UI complexity until measured needs justify them.
10. **Reproducible evaluation** — every optimization must be tested against explicit tasks and baselines.
