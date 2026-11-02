# Historical Merkle construction limitations

**Editorial correction: 2 November 2026.** This reference PoC preserves the
historical algorithm that duplicates the last node at an odd-sized level.
It uses the `0x00` leaf and `0x01` internal-node hash prefixes, but it is not the
split construction in [RFC 9162 §2.1.1](https://www.rfc-editor.org/rfc/rfc9162.html#section-2.1.1)
(which replaces RFC 6962). In that construction, a non-singleton input is split
at the largest power of two strictly below the leaf count.

For three already-hashed leaves `a`, `b`, `c`, let
`N(left, right) = SHA256(0x01 || left || right)`.

| Construction | Three-leaf root |
|--------------|-----------------|
| Historical PoC | `N(N(a,b), N(c,c))` |
| RFC 6962/9162 split tree | `N(N(a,b), c)` |

The historical root for three inputs is therefore also the root for four inputs
whose last two entries are identical. This is ambiguity in the tree construction,
not a SHA-256 collision. A matching root alone cannot authenticate the true leaf
count or prove that every real-world event was recorded. Hash consistency also
does not establish trusted signers, external anchoring or VCP/VAP conformance.

This correction preserves prior event bytes, roots and proof paths. It does not
silently migrate or re-sign historical evidence. A future RFC construction needs
explicit versioning, new vectors and compatibility rules.

The PoC consistency-proof API is unimplemented. `generate` raises
`NotImplementedError`; `verify` returns `False` for all inputs, meaning **not
verified**, not a cryptographic finding that a supplied proof is invalid. Do not
use that boolean interface to report verified append-only consistency.
