# CI preparation and verification — 17 November 2026

Changes are organized into logical local commits with English subjects and bodies,
using the owner's existing Git identity without co-author trailers. This is not
a push or deployment.

| Local check                      | Result                                                                    |
| -------------------------------- | ------------------------------------------------------------------------- |
| Python 3.13, complete backend    | 1841 passed, zero skipped, 98.01% combined line/branch coverage           |
| Python 3.14, complete backend    | 1841 passed, zero skipped, 98.85% combined line/branch coverage           |
| CI report/readiness helper tests | 5 passed                                                                  |
| Frontend                         | 30 Vitest tests, JUnit/no-skips gate, formatting and TypeScript passed    |
| Playwright CI configuration      | All 6 browser scenarios collected with CI reporters/Chromium settings     |
| Workflow                         | YAML/job graph and actionlint passed                                      |
| Production images                | Backend and frontend builds passed                                        |
| Production Compose               | Fresh isolated stack and committed check_compose_stack.py scenario passed |

Python 3.13 used a separate temporary virtualenv; 3.14 used the development
environment. Coverage output was isolated per interpreter. Tests used dedicated
PostgreSQL/Redis and separate Mailpit instances, without development data.

The production helper checked spoofed ingress/IP-list rejection, CSRF, registration
and delivery, resend invalidation, confirmation, login with HttpOnly/Secure cookies,
profile and wallet creation. PostgreSQL contained the verified trusted IP and
User-Agent. Maintenance --dry-run passed. Temporary stack/volumes were removed.

The browser suite was not rerun locally in this change; collection is not browser
execution. The Actions E2E job installs Chromium and runs all six journeys against
fresh services, with failure screenshots/traces. First hosted execution requires
pushing the commits.

Production SES, actual Nginx/TLS, VPS deployment, branch protection and load
benchmarking remain separate tasks. See [CI](ci.md) and [deployment](deployment.md).
