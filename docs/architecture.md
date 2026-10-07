# VCP v1.1 Three-Layer Architecture

This document describes design targets for the TradingView PoC. The bundled Evidence Pack is NON-CERTIFIED and does not establish Silver conformance. Layer 3 is not implemented with real external evidence; the OpenTimestamps, Bitcoin and TSA providers are simulation stubs. The bundled verifier does not verify signatures. Diagrams, benefits and mappings below describe intended capabilities, not validated properties of this pack.

## Overview

VCP v1.1 introduces a **Three-Layer Architecture** that provides progressive levels of tamper-evidence and verifiability:

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: External Verifiability                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  External Timestamp Anchor (OpenTimestamps / Bitcoin)     │  │
│  │  - Proves existence at a specific point in time           │  │
│  │  - Independent third-party verification                   │  │
│  │  - Immutable public record                                │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: Collection Integrity                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  RFC 6962 Merkle Tree + PrevHash Chain                    │  │
│  │  - Detects missing events (completeness)                  │  │
│  │  - Efficient verification (O(log n))                      │  │
│  │  - Single root hash represents entire collection          │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: Event Integrity                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  SHA-256 Hash + Ed25519 Signature                         │  │
│  │  - Detects modification of individual events              │  │
│  │  - Non-repudiation via digital signature                  │  │
│  │  - Canonical JSON serialization (RFC 8785)                │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Layer 1: Event Integrity

### Purpose
Ensures individual events have not been modified after creation.

### Implementation

#### Canonical JSON (RFC 8785 JCS)
```python
def to_canonical_json(event):
    """Convert event to canonical JSON format."""
    canonical = {
        "account_id": event.account_id,
        "clock_sync": event.clock_sync,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "payload": sort_nested(event.payload),
        "policy_id": event.policy_id,
        "system_id": event.system_id,
        "tier": event.tier,
        "timestamp": event.timestamp,
        "vcp_version": event.vcp_version,
    }
    return json.dumps(canonical, sort_keys=True, separators=(',', ':'))
```

#### SHA-256 Hash
```python
event_hash = SHA256(canonical_json(event))
```

#### Ed25519 Signature
```python
signature = Ed25519_Sign(private_key, event_hash)
```

### Tamper Detection
- Any modification to event data changes the hash
- Signature becomes invalid if hash changes

---

## Layer 2: Collection Integrity

### Purpose
Ensures no events have been omitted, inserted, or reordered.

### Implementation

#### RFC 6962 Merkle Tree

Domain separation prefixes prevent second-preimage attacks:

```python
LEAF_PREFIX = b'\x00'
INTERNAL_PREFIX = b'\x01'

def leaf_hash(data):
    return SHA256(LEAF_PREFIX + data)

def internal_hash(left, right):
    return SHA256(INTERNAL_PREFIX + left + right)
```

#### Tree Construction

```
                    Merkle Root
                   /           \
              Hash(0,1)       Hash(2,3)
             /       \       /       \
         Leaf(0)  Leaf(1) Leaf(2)  Leaf(3)
            |        |       |        |
         Event0   Event1  Event2   Event3
```

#### PrevHash Chain (Optional in v1.1)

```
Event[0] ← Event[1] ← Event[2] ← Event[3]
         prev_hash    prev_hash   prev_hash
```

Each event stores the hash of the previous event, creating a linked chain.

### Tamper Detection
- **Deletion**: Merkle root changes, sequence gaps appear
- **Insertion**: Merkle root changes, prev_hash breaks
- **Reordering**: prev_hash chain breaks

---

## Layer 3: External Verifiability

### Purpose
Proves the event collection existed at a specific point in time, verifiable by independent third parties.

### Implementation

#### Silver Tier Target (Not Met by This Evidence Pack)
- **Required Anchor Interval**: Every 24 hours
- **Bundled Evidence**: Local anchor only
- **External Providers**: Simulation stubs; no real external proof included

#### Intended Anchor Process (Not Implemented)
```
1. Collect events for 24-hour period
2. Compute Merkle root of collection
3. Submit Merkle root to OpenTimestamps calendars
4. Receive timestamp proof
5. Proof gets upgraded to Bitcoin blockchain
```

#### Verification
```python
def verify_anchor(merkle_root, ots_proof):
    """Verify timestamp proof against Bitcoin blockchain."""
    # OTS proof contains:
    # - Calendar server attestations
    # - Bitcoin block header reference
    # - Merkle path to block header
    return ots_verify(merkle_root, ots_proof)
```

### Benefits
- **Immutable**: Bitcoin blockchain is practically immutable
- **Independent**: No trust required in the data creator
- **Public**: Anyone can verify using public blockchain data

---

## TradingView Integration Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  TradingView Pine Script                                        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Strategy generates trading signals                       │  │
│  │  ↓                                                        │  │
│  │  Format as VCP v1.1 JSON payload                          │  │
│  │  ↓                                                        │  │
│  │  Send via Webhook alert()                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │ HTTPS POST (Webhook)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  VCP Sidecar                                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  1. Receive event via FastAPI                             │  │
│  │  2. Apply canonical transformation (RFC 8785)             │  │
│  │  3. Compute SHA-256 hash                                  │  │
│  │  4. Sign with Ed25519                                     │  │
│  │  5. Add to Merkle tree                                    │  │
│  │  6. Store event with metadata                             │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          ↓                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Periodic Anchor (24h for Silver Tier)                    │  │
│  │  - Compute final Merkle root                              │  │
│  │  - Submit to OpenTimestamps                               │  │
│  │  - Store anchor proof                                     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Security Properties

| Attack Type | Layer 1 | Layer 2 | Layer 3 |
|-------------|---------|---------|---------|
| Event Modification | ✅ Detected | ✅ Detected | ✅ Detected |
| Event Deletion | ❌ | ✅ Detected | ✅ Detected |
| Event Insertion | ❌ | ✅ Detected | ✅ Detected |
| Backdating | ❌ | ❌ | ✅ Detected |
| Repudiation | ✅ Prevented | ✅ Prevented | ✅ Prevented |

---

## Illustrative Design Mapping (Not a Compliance Assessment)

| Regulation | Requirement | VCP Layer |
|------------|-------------|-----------|
| EU AI Act Art. 12 | Event logging | Layer 1 |
| EU AI Act Art. 12 | Tamper-evidence | Layer 1+2 |
| MiFID II RTS 25 | Audit trail | Layer 1 |
| MiFID II RTS 25 | Completeness | Layer 2 |
| MiFID II RTS 25 | Timestamp accuracy | Layer 3 |
| GDPR | Data integrity | Layer 1+2 |

---

## References

- [RFC 6962: Certificate Transparency](https://www.rfc-editor.org/rfc/rfc6962)
- [RFC 8785: JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)
- [VCP Specification v1.1](https://github.com/veritaschain/vcp-spec/tree/main/spec/v1.1)
- [OpenTimestamps Protocol](https://opentimestamps.org)

---

**VeritasChain Standards Organization (VSO)**  
*"Verify, Don't Trust."*
