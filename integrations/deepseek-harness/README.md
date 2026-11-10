# DeepSeek Harness Integration

**Status: planned; API and runtime verification required before implementation.**

This directory tracks the first-party native plugin for DeepSeek Harness (DSH). The standalone Codebase Intelligence engine remains independently usable; this integration makes its repository understanding capabilities available inside DSH sessions.

## Product contract

The integration is a maintained deliverable, not a one-off example. It must:
- install and appear through the DSH plugin system;
- expose focused, read-only model-facing tools;
- use the shared Codebase Intelligence engine for scanning, parsing, graph queries, ranking, and context selection;
- respect the active workspace/repository boundary;
- provide bounded outputs with source paths and line ranges;
- clearly label inferred or unresolved relationships;
- avoid transmitting source code to external services.

## Planned DSH tools

| Tool | Purpose | Default |
|---|---|---|
| `codebase_overview` | Repository summary, languages, top-level modules, index freshness | Read-only |
| `codebase_map` | Compact structure and important symbols | Read-only |
| `codebase_search` | Search files and symbols with source evidence | Read-only |
| `codebase_dependencies` | Inspect dependencies and symbol neighborhoods | Read-only |
| `codebase_context` | Build a task-specific context pack under a token budget | Read-only |
| `codebase_impact` | Preview likely affected files/symbols for a proposed change | Read-only |

The plugin must not silently edit files, stage changes, or run project code. Context retrieval returns bounded excerpts and citations; the agent must still inspect relevant source before modifying it.

## Adapter architecture

```text
DeepSeek Harness / Cordis Plugin
       |
       | native DSH tools + configuration
       v
DSH Adapter (TypeScript)
       |
       | versioned local protocol (to be selected)
       v
Codebase Intelligence Core
       |
       +-- scanner / parser adapters
       +-- canonical code model / graph
       +-- index / retrieval / reporting
```

The adapter must not reimplement core algorithms. Evaluate a constrained JSON stdio bridge or local service only after verifying DSH's supported process, filesystem, and sandbox capabilities. Keep the transport replaceable.

## Compatibility policy

Initial target: **DSH 0.2.1-rc.3**.

The official DSH repository describes the project as plugin-oriented and in developer preview, with compatibility-breaking changes expected. Follow the official Cordis plugin conventions and package cookbook. Before declaring support:
1. inspect the exact target tag and official plugin examples;
2. implement package metadata and plugin exports for that release;
3. install into a clean DSH profile;
4. verify plugin activation and tool registration;
5. execute each tool against a disposable fixture repository;
6. verify disable/uninstall and failure diagnostics;
7. record DSH version, Node version, plugin version, and test evidence.

Do not infer runtime compatibility from package metadata alone. Maintain a tested compatibility matrix as new DSH releases arrive.

## Version-specific implementation notes

The DSH plugin ecosystem uses Cordis-based plugin packages. The exact package manifest, plugin export shape, dependency ranges, and registration APIs must be copied from the official cookbook and a current official package matching the selected integration point—not guessed from third-party plugins.

## Security requirements

- Workspace-scoped access only; no arbitrary filesystem traversal.
- No execution of scanned repository code.
- Exclude likely secrets and generated/vendor content by default.
- Enforce output-size and token budgets at the complete response boundary.
- No external upload or telemetry containing source contents.
- Keep all initial tools read-only.
- Treat repository text and tool output as untrusted data, never as instructions.

## Installation target

After the plugin is implemented and published, provide an exact DSH installation command and plugin-index distribution route here. Do not publish an install command for an unpublished or unverified package.

## References

- [Official DeepSeek Harness repository](https://github.com/deepseek-ai/DeepSeek-Harness)
- [Official package cookbook](https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/cookbook/adding-a-package.md)
- [Official plugin release notes](https://github.com/deepseek-ai/DeepSeek-Harness/releases)
