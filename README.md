# VCP TradingView Reference Trading Agent (VCP-TV-RTA)

[**English**](README.md) | [日本語](README.ja.md)

[![VCP v1.1](https://img.shields.io/badge/VCP-v1.1-blue)](https://github.com/veritaschain/vcp-spec)
[![Non-certified PoC](https://img.shields.io/badge/Status-Non--certified_PoC-orange)](DISCLAIMER.md)
[![License CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![TradingView](https://img.shields.io/badge/TradingView-Pine%20Script%20v5-131722)](https://www.tradingview.com/)

> **"Verify, Don't Trust."** — AI needs a Flight Recorder

VCP-TV-RTA is a **non-certified proof of concept (PoC)** for TradingView-based algorithmic trading audit trails, targeting VCP v1.1 Silver. **The bundled Evidence Pack does not establish Silver compliance.** It contains a local anchor only; no independently verifiable external anchor proof is included. Third parties can reproduce the limited internal integrity checks described below.

---

## Security and tree-construction correction — 2 November 2026

Set a private `VCP_WEBHOOK_SECRET` (or `server.webhook_secret`) before starting the
sidecar. An empty or missing secret stops startup before any event/key/anchor
component is initialized. All `/vcp/` endpoints require the
`X-VCP-Webhook-Secret` header. Event ingestion also accepts a top-level
`webhook_secret` JSON field for a private alert template; this transport field
is excluded from the recorded and signed event. If both credentials are sent,
both must match. Credentials are compared with `hmac.compare_digest`.

Existing unauthenticated alerts are rejected. Configure the credential in a
private sender/alert template, or use a trusted relay that adds the header.
The bundled Pine strategy does not insert a secret. Do not put secrets in a
public script or webhook URL. See [integration instructions](docs/INTEGRATION.md).
`/health` and API documentation remain public. This shared-secret mechanism does
not provide replay protection, per-client roles or production readiness.

Browser CORS is disabled unless `server.allowed_origins` lists explicit HTTP(S)
origins. Wildcards are rejected and credentialed CORS is disabled. CORS is not
authentication; server-to-server webhooks do not need it.

The Merkle builder retains the historical odd-node duplication algorithm and
RFC-style domain prefixes. It is **not** the RFC 6962/9162 split construction.
The unimplemented consistency-proof verifier now returns `False` (not verified),
and generation raises `NotImplementedError`. Historical evidence and root/proof
construction are unchanged. See [the construction limits](docs/MERKLE_LIMITATIONS.md).

Forced and periodic anchoring now retain the pending batch when a provider
returns failure, raises an exception, or the attempt is cancelled. The forced
endpoint returns HTTP 502 for an unconfirmed result. Each attempt seals one
batch while new events enter a separate tree; retries use the sealed batch
first. Only explicit provider success for that batch's root retires it. A local
provider's success still means local recording only, not external assurance.
Pending counts include both trees, and the status root identifies the oldest
batch. This bookkeeping is in memory in one process: restart recovery,
coordination across workers and an archive of retired inclusion proofs are
not implemented. See [anchoring behavior](docs/INTEGRATION.md#force-anchor-testing-only).

## Overview

This Evidence Pack demonstrates selected VCP mechanisms integrated with TradingView's Pine Script environment. It is not production-ready or a complete conformance demonstration. The implementation captures algorithmic trading decisions and execution events using a **sidecar architecture** that operates independently of the TradingView platform via webhooks.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  TradingView                                                    │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  Pine Script Strategy (vcp_silver_strategy.pine)     │       │
│  │  - Event capture (Entry/Exit/Position Change)        │       │
│  │  - PoC JSON payloads (target tier: Silver)           │       │
│  │  - Webhook-based transmission                        │       │
│  └──────────────────────┬───────────────────────────────┘       │
└─────────────────────────┼───────────────────────────────────────┘
                          │ Webhook (HTTPS POST)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  VCP Sidecar (Python FastAPI)                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────┐ │
│  │ FastAPI     │→ │ Canonical   │→ │ Merkle Tree │→ │ Anchor  │ │
│  │ Receiver    │  │ Transform   │  │ Builder     │  │ Service │ │
│  │             │  │ (RFC 8785)  │  │ (PoC tree)  │  │         │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────┘ │
│        │                                                 ↓      │
│        ▼                                    ┌───────────────────┐│
│  ┌─────────────┐                            │ OpenTimestamps /  ││
│  │ Ed25519     │                            │ Bitcoin / TSA     ││
│  │ Signature   │                            └───────────────────┘│
│  └─────────────┘                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## VCP v1.1 Design Targets (Not Evidence of Implementation Compliance)

| Feature | v1.0 | v1.1 |
|---------|------|------|
| **Three-Layer Architecture** | - | ✅ NEW |
| **External Anchor (Silver)** | OPTIONAL | **REQUIRED** |
| **Policy Identification** | - | **REQUIRED** |
| **PrevHash** | REQUIRED | OPTIONAL |
| **Completeness verification (omission detection at anchor granularity)** | - | ✅ NEW |

---

## Repository Structure

```
vcp-tradingview-rta-reference/
├── evidence/
│   ├── evidence_index.json
│   ├── 01_trade_logs/
│   │   └── vcp_tv_events.jsonl
│   ├── 02_verification/
│   │   └── verification_report.txt
│   ├── 03_tamper_detection/
│   │   ├── tamper_detection_test.py
│   │   └── tampered_chain.jsonl
│   └── 04_anchor/
│       ├── security_object.json
│       ├── anchor_reference.json
│       └── public_key.json
├── sidecar/
│   ├── main.py
│   ├── vcp_core.py
│   ├── merkle.py
│   ├── anchor.py
│   ├── keygen.py
│   ├── config/settings.yaml
│   └── tests/test_vcp_core.py
├── tradingview/
│   ├── vcp_silver_strategy.pine
│   └── vcp_webhook_format.md
├── tools/verifier/
│   └── vcp_verifier.py
├── docs/
│   ├── VERIFICATION_GUIDE.md
│   ├── INTEGRATION.md
│   └── architecture.md
├── examples/
├── CHANGELOG.md
├── DISCLAIMER.md
├── LICENSE
└── README.md
```

---

## Quick Start

```bash
# Clone
git clone https://github.com/veritaschain/vcp-tradingview-rta-reference.git
cd vcp-tradingview-rta-reference

# Install
pip install -r requirements.txt

# Generate keys
python -m sidecar.keygen

# Run server
export VCP_WEBHOOK_SECRET="$(openssl rand -hex 32)"
python -m sidecar.main
```

---

## Quick Verification

```bash
python tools/verifier/vcp_verifier.py \
    evidence/01_trade_logs/vcp_tv_events.jsonl \
    -s evidence/04_anchor/security_object.json \
    -a evidence/04_anchor/anchor_reference.json
```

---

## Evidence Status and Verification Scope

- The 40-event sample passes the bundled event-hash, sequence, PrevHash, Merkle-root and event-count checks. These checks do not prove collection completeness against an independent source.
- `anchor_reference.json` is `local`: it binds the same root locally but does not satisfy the required Silver external anchor. The OpenTimestamps, Bitcoin and TSA providers are simulation stubs, not usable external proof backends. Their simulated results must not be reported as successful external anchoring.
- The verifier does not verify Ed25519 signatures, signer identity, trusted external time, the 24-hour anchor cadence, or full VCP conformance. It reproduces the PoC serialization and Merkle algorithm; it is not a general RFC 8785/RFC 6962 validator.
- The command above exits **2** for the bundled pack: internal integrity passed, **Silver not established**. Exit **1** means invalid evidence or an input error. Add `--integrity-only` to allow exit **0** for the limited internal checks; this never certifies Silver.
- Existing event fields such as `tier: "SILVER"` are preserved as hashed source data and represent the intended tier, not an assessed result.
- Sample event times are in January 2025; local artifact metadata is dated January 2026. The original pack creation time is unknown. Its unsupported 2025 `created_at` value is retained in correction provenance, not asserted as fact. See [the verification guide](docs/VERIFICATION_GUIDE.md).

## License

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (Evidence Pack)  
MIT License (Implementation Code)

---

**VeritasChain Standards Organization (VSO)**  
*"Verify, Don't Trust."*

## License scope clarification — 2 November 2026

Documentation remains CC BY 4.0. First-party code, scripts, code examples and schemas additionally offer [Apache-2.0](LICENSE-CODE); existing licenses and third-party notices remain in effect. See [LICENSE](LICENSE) for the scope and preserved prior terms. This editorial licensing note does not change protocol requirements or claim conformance.
