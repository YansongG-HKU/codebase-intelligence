/**
 * dsh-codebase-intelligence — 01-styles
 *
 * One embedded stylesheet for the panel. Every selector is namespaced under
 * `.cbi-*`, no global CSS and no variable overrides: the theme is expressed as
 * DSH design tokens with safe light-theme fallbacks, so claude-mode and every
 * other DSH theme style the panel without any hard dependency.
 */

    const STYLES = `
.cbi-root {
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
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--cbi-border);
  border-radius: var(--cbi-radius-lg);
  background: var(--cbi-layer1);
  color: var(--cbi-ink);
  text-align: left;
  cursor: pointer;
  min-width: 0;
}
@media (hover: hover) { .cbi-guide-entry:hover { background: var(--cbi-hover); border-color: var(--cbi-border2); } }
.cbi-guide-entry:focus-visible { outline: 2px solid var(--cbi-brand); outline-offset: 1px; }
.cbi-guide-title { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; }
.cbi-guide-desc { font-size: 11px; color: var(--cbi-ink3); overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }

/* Scrollbars --------------------------------------------------------- */
.cbi-root ::-webkit-scrollbar { width: 8px; height: 8px; }
.cbi-root ::-webkit-scrollbar-thumb { background: var(--cbi-border2); border-radius: 4px; }
.cbi-root ::-webkit-scrollbar-track { background: transparent; }
`
