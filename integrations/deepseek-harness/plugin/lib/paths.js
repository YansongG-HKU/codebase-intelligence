/**
 * Path resolution for `dsh-codebase-intelligence`.
 *
 * The plugin knows two locations at runtime:
 *
 * - the repository checkout it lives in (`integrations/deepseek-harness/plugin`
 *   → repository root three levels up), used to find the Python package under
 *   `src/` in a source checkout;
 * - the per-user plugin data directory (default `<DSH_HOME>/codebase-intelligence`)
 *   that holds the engine's index cache. Nothing is ever written to a user's
 *   workspace: the engine is always handed `--cache-dir <dataDir>/indexes/<hash>`.
 *
 * @module dsh-codebase-intelligence/paths
 */

import { createHash } from 'node:crypto'
import { existsSync, realpathSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

/** Absolute path of the plugin package directory. */
export const PLUGIN_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/** Repository root in a source checkout (plugin → deepseek-harness → integrations → repo). */
export const REPO_ROOT = resolve(PLUGIN_DIR, '..', '..', '..')

/** Python source directory in a source checkout (`<repo>/src`). */
export const CORE_SRC_DIR = join(REPO_ROOT, 'src')

/** Directory name of the Python package inside its import root. */
const CORE_PACKAGE_NAME = 'codebase_intelligence'

/**
 * Resolve the directory that must be on `PYTHONPATH` so that
 * `python -m codebase_intelligence.cli` works.
 *
 * `config.corePath` wins when set (it may be `<repo>/src`, a checkout's `src`,
 * or the package directory itself). Otherwise the repository's own `src/` is
 * used when it contains the package. Returns `null` when the engine is meant to
 * be a pip-installed package: the probe then relies on the interpreter's own
 * `sys.path`, and no `PYTHONPATH` entry is added.
 *
 * @param {{corePath?: string | null}} cfg resolved config
 * @returns {string | null} import root or null
 */
export function resolveCorePath(cfg) {
  const configured = typeof cfg?.corePath === 'string' && cfg.corePath.trim().length > 0 ? cfg.corePath.trim() : null
  if (configured !== null) {
    const absolute = isAbsolute(configured) ? configured : resolve(REPO_ROOT, configured)
    return importRootOf(absolute)
  }
  return importRootOf(CORE_SRC_DIR)
}

/**
 * Normalize a core directory to the directory containing `codebase_intelligence`.
 * Returns null when no plausible package exists (allowing pip-installed use).
 *
 * @param {string} directory
 * @returns {string | null}
 */
function importRootOf(directory) {
  if (existsSync(join(directory, CORE_PACKAGE_NAME, 'cli.py'))) return directory
  if (existsSync(join(directory, 'cli.py')) && directory.replace(/[\\/]+$/u, '').endsWith(CORE_PACKAGE_NAME)) {
    return dirname(directory)
  }
  return null
}

/**
 * Canonical, case-folded form of an absolute root used for cache hashing.
 *
 * Windows paths are case-insensitive and the same directory may be reached
 * with different casing or through a junction; the real path is used when it
 * can be resolved so two spellings share one cache directory.
 *
 * @param {string} root absolute directory path
 * @returns {string} stable cache identity
 */
export function canonicalRoot(root) {
  let absolute = resolve(String(root))
  try {
    absolute = realpathSync.native(absolute)
  } catch {
    /* a missing root is reported earlier by the service; hash the resolved form */
  }
  const normalized = absolute.split(sep).join('/').replace(/\/+$/u, '')
  return process.platform === 'win32' ? normalized.toLowerCase() : normalized
}

/**
 * Stable 16-hex cache bucket for a workspace root.
 *
 * @param {string} root absolute workspace root
 * @returns {string} short hex digest
 */
export function rootHash(root) {
  return createHash('sha256').update(canonicalRoot(root), 'utf8').digest('hex').slice(0, 16)
}

/**
 * The engine's index cache directory for one workspace.
 *
 * Always under the plugin data directory, never inside the workspace.
 *
 * @param {{dataDir: string}} cfg resolved config
 * @param {string} root absolute workspace root
 * @returns {string} absolute cache directory
 */
export function cacheDirFor(cfg, root) {
  return join(cfg.dataDir, 'indexes', rootHash(root))
}

/**
 * Whether an absolute path is the root itself or lives below it.
 *
 * @param {string} root absolute root directory
 * @param {string} candidate absolute candidate path
 * @returns {boolean}
 */
export function isWithin(root, candidate) {
  const rootPath = resolve(root)
  const candidatePath = resolve(candidate)
  if (candidatePath === rootPath) return true
  const prefix = rootPath.endsWith(sep) ? rootPath : `${rootPath}${sep}`
  return candidatePath.startsWith(prefix)
}
