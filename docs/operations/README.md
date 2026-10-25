# Operations

How to configure this platform, watch it, and put it into production. Three documents, in the order
you need them.

| Document | For | Read it when |
| --- | --- | --- |
| [Configure the API Gateway](configure.md) | Whoever installs it | Setting the platform up from nothing, or onboarding the first partner |
| [Monitoring and error checking](monitoring-and-errors.md) | Support and operations | Daily, and whenever somebody reports a failure |
| [Hosting in production](production.md) | Infrastructure, and whoever signs off the go-live | Before a production deployment |

These are also published as a shared document:
<https://claude.ai/artifact/XNVaCsEKsxnpfgJKH7SNqY>. The copies here are the ones that version with
the code; if the two disagree, these are right.

Related reference in this repository:

- [`infra/postgres/diagnostics.sql`](../../infra/postgres/diagnostics.sql) — sixteen read-only
  queries behind the error-checking document.
- [`infra/.env.example`](../../infra/.env.example) — every value the stack reads, annotated.
- [`infra/sanity.sh`](../../infra/sanity.sh) — the 22-check verification of a running stack.
- [`docs/architecture.md`](../architecture.md) — the component view.
- [`docs/brd-traceability.md`](../brd-traceability.md) — requirement-by-requirement status.
- [`CHANGELOG.md`](../../CHANGELOG.md) — what changed, when and why.
