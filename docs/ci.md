# Continuous integration

Updated 17 November 2026. [.github/workflows/ci.yml](../.github/workflows/ci.yml)
runs on pushes, pull requests and manual dispatch. It uses read-only repository
permissions and does not deploy, push commits or require production credentials.
Concurrent runs for the same branch/PR replace older runs.

| Job                           | Required checks                                                                                                                                                               |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend, Python 3.13 and 3.14 | Poetry lock validation, strict pytest, real PostgreSQL 17/Redis 8/Mailpit, coverage at least 91%, no skipped tests                                                            |
| Frontend                      | Locked npm install, Prettier, Next route types, TypeScript, Vitest JUnit/no-skips gate, production build                                                                      |
| Browser E2E                   | Workflow lint, real API/email worker/Next.js, migrations, Chromium journeys, JUnit/no-skips gate                                                                              |
| Containers                    | Compose validation, both production builds/resources, isolated production stack, ingress/IP/CSRF, email/resend/confirm/login, secure cookies, wallets and maintenance preview |
| CI required checks            | Fails if any preceding job failed, was cancelled or skipped                                                                                                                   |

Backend matrix jobs have independent services and coverage artifacts. JUnit gates
reject skipped tests and empty reports. CI report/readiness helpers have stdlib
unit tests. [actionlint v1.7.12](https://github.com/rhysd/actionlint/releases/tag/v1.7.12)
is pinned with a verified archive SHA-256.

Browser tests use one worker, no automatic retries and forbidOnly. CI installs
Playwright Chromium; ordinary local runs retain installed Chrome. Bounded readiness
polling checks processes before tests start. Failures retain screenshots and traces.

Production tests use a dedicated fincore-ci-* Compose project, synthetic .example
identities, Mailpit, a dummy proxy secret and a private API. They simulate trusted
TLS ingress over loopback HTTP; actual Nginx/DNS are not changed. An always-running
cleanup removes temporary containers, networks and volumes.

## Reports and required status

Artifacts are retained for 14 days:

- backend-reports-python-3.13 and backend-reports-python-3.14: JUnit/XML/HTML coverage;
- frontend-unit-report: Vitest JUnit;
- browser-reports: Playwright HTML/JUnit, screenshots/traces and process logs;
- container-logs: Compose service logs.

Artifacts contain synthetic test data. No real SMTP/database/JWT secrets are used.
After pushing and obtaining a successful run, configure branch protection to require
**CI required checks**. This change does not modify GitHub administration settings.
Local validation is separate from an actual hosted Actions run.

## Local verification

Prepare dedicated services using backend/tests/integration/persistence/README.md:

```bash
python3 -m unittest discover -s .github/tests -p 'test_*.py'
cd backend
poetry check --lock
poetry run pytest --cov --cov-fail-under=91 --junitxml=reports/pytest.xml
python3 ../.github/scripts/check_pytest_report.py reports/pytest.xml
```

From frontend:

```bash
npm ci
npm run format:check
npx next typegen
npm run typecheck
npm test
npm run build
```

Run browser tests only with the separately prepared stack in
[frontend README](../frontend/README.md). Local tests write synthetic records to
the running API's database; Actions provisions its own database. The production
helper requires the container job's dedicated environment, not a live deployment.
