# Deployment runbook

Use this runbook before every release of the fixture dashboard.

## Release checklist

1. Run the test suite.
2. Build the dashboard and worker packages.
3. Run `automation/deploy.sh --deploy production`.
4. Check the aggregated metrics and worker queue.

## Rollback

Re-deploy the previous known-good build and verify the dashboard metrics.
