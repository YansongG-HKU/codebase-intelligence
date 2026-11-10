"""Repository discovery: deterministic file walking under a frozen scan policy.

Public surface (see ``docs/SPEC.md`` section 5)::

    from codebase_intelligence.scanner import (
        ScanPolicy, ScanResult, default_policy, detect_language,
        policy_fingerprint, scan_repository,
    )

The scanner reads repository bytes only; it never imports, evaluates or
executes scanned code, and it never reads outside the resolved repository root.
"""

from codebase_intelligence.scanner.discovery import (
    SKIP_REASONS,
    ScanResult,
    detect_language,
    is_secret_name,
    scan_repository,
)
from codebase_intelligence.scanner.policy import (
    DEFAULT_EXCLUDES,
    DEFAULT_INDEX_DIR_NAME,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_SECRET_PATTERNS,
    INCLUDE_SECRETS_ENV,
    SECRET_PATTERNS,
    ScanPolicy,
    default_policy,
    include_secrets_from_env,
    policy_fingerprint,
)

__all__ = [
    "DEFAULT_EXCLUDES",
    "DEFAULT_INDEX_DIR_NAME",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_SECRET_PATTERNS",
    "INCLUDE_SECRETS_ENV",
    "SECRET_PATTERNS",
    "SKIP_REASONS",
    "ScanPolicy",
    "ScanResult",
    "default_policy",
    "detect_language",
    "include_secrets_from_env",
    "is_secret_name",
    "policy_fingerprint",
    "scan_repository",
]
