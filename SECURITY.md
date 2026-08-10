# Security Policy

## Supported versions

Security fixes are provided for the latest published release of
`listmonk-mcp-bridge`. Older releases are not supported; users should upgrade
to the latest release before reporting an issue when possible.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Older releases | No |

## Reporting a vulnerability

Please do not report suspected vulnerabilities in a public issue, pull
request, or discussion.

Use [GitHub's private vulnerability reporting form](https://github.com/mnbro/listmonk-mcp-bridge/security/advisories/new)
to contact the maintainers privately. Include, where applicable:

- The affected release or commit.
- The impact, attack scenario, and required preconditions.
- Reproduction steps or a minimal proof of concept.
- Relevant configuration or logs, with sensitive information removed.
- Any suggested mitigation or fix.
- Whether you would like public credit after disclosure.

Never include live Listmonk credentials, access tokens, subscriber data,
email content, or other personal data in a report. Revoke any exposed secret
immediately and mention the exposure using redacted values only. See the
project's [authentication guidance](docs/authentication.md) and
[safeguards](docs/safeguards.md) for its existing security model.

The maintainers will acknowledge the report, assess its severity and
reproducibility, and coordinate remediation and disclosure through the private
advisory. Resolution time depends on the issue's impact and complexity.

## Scope

Examples of issues that are in scope include:

- Exposure or misuse of Listmonk credentials and authentication data.
- Bypasses of read-only mode, confirmation controls, or destructive-operation
  safeguards.
- Unauthorized email sending, scheduling, or subscriber modification.
- Disclosure of sensitive subscriber, campaign, configuration, or audit data.
- Bypasses of redaction, idempotency, request-size, or rate-limit protections.
- Vulnerable dependencies, build pipelines, or container images maintained by
  this repository.

Vulnerabilities in Listmonk itself, MCP clients, deployment platforms, or other
third-party services should normally be reported to their respective
maintainers. If it is unclear where responsibility lies, report the issue here
privately and the maintainers will help route it.

## Safe research and coordinated disclosure

Use your own test instance and synthetic data. Do not test against production
or systems you do not own without explicit authorization. Do not send email to
non-consenting recipients, access more data than is necessary to demonstrate
the issue, disrupt service, establish persistence, or make destructive changes.

Stop testing once you have sufficient evidence, protect any data encountered,
and keep the report confidential until a fix and disclosure plan have been
coordinated with the maintainers. Good-faith research that follows this policy
is appreciated.

For ordinary bugs, feature requests, and usage questions that do not involve a
security risk, use the repository's public issue tracker.
