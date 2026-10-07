# Changelog

All notable changes to the VCP TradingView RTA Reference Implementation will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Corrected
- Replaced unsupported Silver / production-ready / complete-evidence claims with non-certified PoC status.
- Split internal integrity results from external assurance; local or unsupported anchors cannot produce Silver success. Default CLI exits 2 when Silver is not established.
- Fail closed on malformed input, missing requested files and mismatched anchor roots; added verifier regression tests.
- Regenerated the evidence report and documented unverified signatures and anchor cadence.
- Set unknown pack creation time to null, preserving the old date in provenance and leaving original evidence bytes unchanged.
- Corrected the initial-release heading to 2026-01-17, the repository import commit date; the original exact pack creation time remains unknown.

## [1.1.0] - 2026-01-17 (repository import date)

### Added
- Initial release of VCP TradingView Reference Implementation
- PoC targeting VCP v1.1 Silver Tier; compliance not established
- Three-layer architecture implementation:
  - Layer 1: Event Integrity (SHA-256 + Ed25519)
  - Layer 2: Collection Integrity (RFC 6962 Merkle Tree)
  - Layer 3: Local anchor and external-provider simulation stubs
- FastAPI-based sidecar for webhook reception
- Pine Script v5 strategy template (`vcp_silver_strategy.pine`)
- PoC evidence sample with limited internal verification tools
- Tamper detection test suite
- Docker deployment configuration
- Bilingual documentation (English/Japanese)

### Features
- Canonical JSON serialization (RFC 8785 JCS)
- Ed25519 digital signatures
- RFC 6962 compliant Merkle Tree with domain separation
- Multiple anchor providers (OpenTimestamps, Bitcoin, TSA, Local)
- Webhook-based event capture from TradingView
- RESTful API for event verification and proof retrieval

### Design Targets (Not Achieved Conformance)
- VCP v1.1 Silver Tier requirements
- External anchoring REQUIRED (24-hour interval)
- Policy identification support
- Collection integrity checks; completeness against an independent source is not established

### Documentation
- VERIFICATION_GUIDE.md for step-by-step verification
- INTEGRATION.md for TradingView setup
- architecture.md explaining three-layer design
- Inline code documentation

### Planned
- Gold Tier implementation (1-hour anchoring)
- Enhanced webhook authentication
- Real-time monitoring dashboard
- Performance optimizations for high-frequency events

---

For more information about VCP versions, see:
- [VCP v1.1 Specification](https://github.com/veritaschain/vcp-spec/tree/main/spec/v1.1)
