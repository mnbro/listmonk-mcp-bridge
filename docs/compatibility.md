# Listmonk API Compatibility

Listmonk currently declares OpenAPI version `1.0.0`, but that value does
not change for every upstream API change. The bridge therefore identifies
the API by a content-addressed contract derived from registered routes,
permissions, the upstream OpenAPI document and relevant Go handler-source
fingerprints.

## Current Development Contract

- Contract: `lm-api:sha256:c66622870912c9a5f7eb0058a151fc6d53bbe51dd2e0321002601b5ee46fc1bd`
- Upstream-declared API version: `1.0.0`
- Source snapshot: [v6.2.0](https://github.com/knadh/listmonk/releases/tag/v6.2.0) at `ef0a75872463f10a4848af6c547d1c057405453a`
- Known Listmonk releases with this contract: `v6.2.0`
- Route decisions: 74 implemented, 30 intentionally omitted, 0 awaiting review

## Bridge Release Matrix

| Bridge release | API contract | Source snapshot | Verification |
| --- | --- | --- | --- |
| [`v0.4.33`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.33) | `lm-api:c66622870912` | [`v6.2.0`](https://github.com/knadh/listmonk/releases/tag/v6.2.0) | `source-verified` |
| [`v0.4.32`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.32) | — | — | `not-recorded` |
| [`v0.4.31`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.31) | — | — | `not-recorded` |
| [`v0.4.30`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.30) | — | — | `not-recorded` |
| [`v0.4.29`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.29) | — | — | `not-recorded` |
| [`v0.4.28`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.28) | — | — | `not-recorded` |
| [`v0.4.27`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.27) | — | — | `not-recorded` |
| [`v0.4.26`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.26) | — | — | `not-recorded` |
| [`v0.4.25`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.25) | — | — | `not-recorded` |
| [`v0.4.24`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.24) | — | — | `not-recorded` |
| [`v0.4.23`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.23) | — | — | `not-recorded` |
| [`v0.4.22`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.22) | — | — | `not-recorded` |
| [`v0.4.21`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.21) | — | — | `not-recorded` |
| [`v0.4.20`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.20) | — | — | `not-recorded` |
| [`v0.4.19`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.19) | — | — | `not-recorded` |
| [`v0.4.18`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.18) | — | — | `not-recorded` |
| [`v0.4.17`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.17) | — | — | `not-recorded` |
| [`v0.4.16`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.16) | — | — | `not-recorded` |
| [`v0.4.15`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.15) | — | — | `not-recorded` |
| [`v0.4.14`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.14) | — | — | `not-recorded` |
| [`v0.4.13`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.13) | — | — | `not-recorded` |
| [`v0.4.12`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.12) | — | — | `not-recorded` |
| [`v0.4.11`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.11) | — | — | `not-recorded` |
| [`v0.4.10`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.10) | — | — | `not-recorded` |
| [`v0.4.9`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.9) | — | — | `not-recorded` |
| [`v0.4.8`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.8) | — | — | `not-recorded` |
| [`v0.4.7`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.7) | — | — | `not-recorded` |
| [`v0.4.6`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.6) | — | — | `not-recorded` |
| [`v0.4.5`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.5) | — | — | `not-recorded` |
| [`v0.4.4`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.4) | — | — | `not-recorded` |
| [`v0.4.3`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.3) | — | — | `not-recorded` |
| [`v0.4.2`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.2) | — | — | `not-recorded` |
| [`v0.4.1`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.1) | — | — | `not-recorded` |
| [`v0.4.0`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.4.0) | — | — | `not-recorded` |
| [`v0.3.0`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.3.0) | — | — | `not-recorded` |
| [`v0.2.0`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.2.0) | — | — | `not-recorded` |
| [`v0.1.13`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.13) | — | — | `not-recorded` |
| [`v0.1.12`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.12) | — | — | `not-recorded` |
| [`v0.1.11`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.11) | — | — | `not-recorded` |
| [`v0.1.10`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.10) | — | — | `not-recorded` |
| [`v0.1.9`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.9) | — | — | `not-recorded` |
| [`v0.1.8`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.8) | — | — | `not-recorded` |
| [`v0.1.7`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.7) | — | — | `not-recorded` |
| [`v0.1.6`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.6) | — | — | `not-recorded` |
| [`v0.1.5`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.5) | — | — | `not-recorded` |
| [`v0.1.4`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.4) | — | — | `not-recorded` |
| [`v0.1.3`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.3) | — | — | `not-recorded` |
| [`v0.1.2`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.2) | — | — | `not-recorded` |
| [`v0.1.1`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.1) | — | — | `not-recorded` |
| [`v0.1.0`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/v0.1.0) | — | — | `not-recorded` |

## Verification Levels

- `runtime-certified`: passed the disposable Listmonk integration suite.
- `source-verified`: routes, schemas and relevant behavior were audited against the named source snapshot.
- `route-compatible`: method and path compatibility was checked statically.
- `not-recorded`: the historical release predates compatibility attestations.
- `incompatible`: a known contract conflict prevents supported operation.

Historical entries remain `not-recorded` unless reproducible evidence is
available. The automation never infers semantic compatibility from dates or
release numbers alone.

Machine-readable records are stored in
[`compatibility/listmonk-api-contract.json`](https://github.com/mnbro/listmonk-mcp-bridge/blob/master/compatibility/listmonk-api-contract.json)
and
[`compatibility/bridge-releases.json`](https://github.com/mnbro/listmonk-mcp-bridge/blob/master/compatibility/bridge-releases.json).
