# Token Accounting, Budgets and Cache-Friendliness

This document explains how Codebase Intelligence spends model tokens, how the
budgets are enforced, and why the integration is designed not to hurt prompt
cache hit rates. Measured numbers live in [BENCHMARKS.md](BENCHMARKS.md).

## 1. What is always paid (prompt surface)

The DSH plugin contributes two static pieces to every agent prompt:

1. Six tool schemas (`name`, description, JSON parameters) — committed as plain
   JavaScript constants. Measured at **1189 estimated tokens** (4756 bytes).
2. One system-prompt section — a single immutable string, registered with
   `interpolate: false`. Measured at **184 estimated tokens** (735 bytes, 98
   words).

Total always-on DSH footprint: **1373 estimated tokens** per session, fixed.
The MCP tool catalogue is smaller (903 tokens) because MCP clients carry the JSON
Schema themselves. The **client panel adds no prompt tokens**: it registers no
tools and no system-prompt text, so these numbers are unaffected by it; panel
data travels over loopback HTTP routes and never enters the model context.

Both pieces are **byte-static**: no workspace, timestamp, config value or runtime
state is interpolated into them, so the prompt prefix is identical on every step
of a session and on future sessions until the plugin version changes. The plugin
unit tests assert the prompt text is static and the schema footprint stays under
2200 tokens.

## 2. What is paid per call (tool outputs)

Every tool takes a `maxTokens` argument (defaults: overview 900, map 1600,
search 1200, dependencies 1200, context 2200, impact 1200; clamped to
64..8000 by the engine, 200..8000 by the plugin). The engine builds the largest
useful payload, measures it, and drops whole rows/excerpts until it fits; it
reports `budgets {maxTokens, tokensEstimated, tokenEstimator}` plus
`omitted`/`truncated` metadata so the model knows what it did not see.

Representative payload sizes on this repository (see BENCHMARKS.md):

| Tool | Budget | Measured | |
|---|---|---|---|
| overview | 900 | 677 | within budget |
| map | 1600 | 1498 | within budget |
| search | 1200 | 1161 | within budget |
| dependencies | 1200 | 1062 | within budget |
| context | 2200 | 2161 | within budget |
| impact | 1200 | 130 | within budget |

The point of the product is to make these calls *replace* large speculative file
reads: one `codebase_context` call returns ranked definitions with `path:line`
citations instead of dozens of whole files.

## 3. Token estimation method

`util.estimate_tokens` implements `chars4-wide-v1`:

- every 4 ASCII characters count as 1 token,
- every non-ASCII character counts as 1 token (CJK ≈ one token per character),
- minimum 1 for any non-empty input.

It is an estimate, not a model tokenizer; no tokenizer is shipped (zero runtime
dependencies) and every payload names the method so callers can calibrate. The
`scripts/bench.py` numbers and the DSH session usage shown in DELIVERY.md are
measured with the same method / the provider's own accounting respectively.

## 4. Why cache hit rates are not hurt

Prompt-cache friendliness requires an identical prefix. The design enforces it:

- tool schemas and the prompt section are static constants;
- tool payloads contain **no** timestamps, durations, absolute paths or
  cache-hit flags; files/symbols/relations are sorted with explicit total orders;
- JSON is canonical (`sort_keys`, `ensure_ascii=False`, `(",", ":")`);
- repeated identical calls return byte-identical payloads (asserted per
  operation in the benchmark), so a replayed tool call does not churn the
  prefix;
- index freshness is expressed as a content fingerprint, not a time value, and
  the plugin memoizes payloads keyed by `(root, args, index fingerprint)` without
  ever surfacing cache state.

Measured in the isolated DSH acceptance session (two turns, same workspace):

- Turn 1: 27.7K tokens, cache hit 43% (cold prefix).
- Session after turn 2: 63,352 tokens, 43,776 cache-read, 18,592 uncached input,
  984 output → **70% cumulative hit**, i.e. the second turn was ~90% cached as
  the static system prefix and previous turns were reused.

That is the expected shape: the plugin adds a fixed, cacheable prefix and
deterministic tool payloads, so steady-state turns keep high hit rates.

## 5. Index cache (not model cache)

Independently of prompt caching, the engine keeps a content-addressed local index
cache: cold builds reparse changed files only, warm builds reuse unchanged files
and produce byte-identical public payloads. On this repository: cold build
`reused=0, reparsed=144`, warm build `reused=144, reparsed=0`, `cacheHit=true`,
identical fingerprint. The DSH plugin stores this cache under
`<DSH_HOME>/codebase-intelligence/indexes/<rootHash>` so the user's repository is
never written to.
