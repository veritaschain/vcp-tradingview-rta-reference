#!/usr/bin/env python3
"""
VCP v1.1 Chain Verifier
VeritasChain Protocol Event Chain Verification Tool

This tool verifies the integrity of VCP v1.1 event chains by checking:
1. Individual event hashes
2. Sequence continuity
3. PrevHash chain integrity
4. Merkle root verification
5. Anchor metadata classification (NOT external proof verification)

This PoC tool does not verify signatures, external timestamps, anchor cadence,
or full VCP conformance. Exit 0 is available only with --integrity-only;
exit 2 means the checked integrity passed but Silver was not established.

Usage:
    python vcp_verifier.py <events.jsonl> [-s security_object.json]

Copyright (c) 2025 VeritasChain Standards Organization
License: MIT
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class VerificationResult:
    """Result of verification for a single event."""
    event_id: str
    valid: bool
    hash_valid: bool
    sequence_valid: bool
    prev_hash_valid: bool
    errors: List[str]


class VCPVerifier:
    """
    VCP v1.1 Event Chain Verifier.
    
    Implements verification of:
    - Event hash integrity
    - Sequence continuity
    - PrevHash chain linking
    - Merkle tree root
    """
    
    # RFC 6962 domain separation prefixes
    LEAF_PREFIX = b'\x00'
    INTERNAL_PREFIX = b'\x01'
    
    def __init__(self, verbose: bool = False):
        """Initialize verifier."""
        self.verbose = verbose
        self.events: List[Dict[str, Any]] = []
        self.security_object: Optional[Dict[str, Any]] = None
        self.anchor_reference: Optional[Dict[str, Any]] = None
    
    def load_events(self, filepath: str) -> int:
        """
        Load events from JSONL file.
        
        Args:
            filepath: Path to events JSONL file
            
        Returns:
            Number of events loaded
        """
        self.events = []
        
        with open(filepath, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError(f"Event on line {line_num} must be an object")
                    self.events.append(event)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON on line {line_num}: {e}") from e
        
        return len(self.events)
    
    def load_security_object(self, filepath: str) -> bool:
        """
        Load security object containing Merkle root and signatures.
        
        Args:
            filepath: Path to security object JSON
            
        Returns:
            True if loaded successfully
        """
        try:
            with open(filepath, 'r') as f:
                self.security_object = json.load(f)
            if not isinstance(self.security_object, dict) or not self.security_object:
                raise ValueError("Security object must be a non-empty JSON object")
            return True
        except Exception as e:
            self.security_object = None
            print(f"Error: Could not load security object: {e}")
            return False

    def load_anchor_reference(self, filepath: str):
        """Load untrusted metadata; a provider name is not an external proof."""
        with open(filepath, 'r') as f:
            anchor = json.load(f)
        if not isinstance(anchor, dict) or not anchor:
            raise ValueError("Anchor reference must be a non-empty JSON object")
        self.anchor_reference = anchor

    def assess_anchor(self, computed_root: Optional[str]) -> Tuple[str, str]:
        """Fail closed: no external-proof backend is implemented by this tool."""
        anchor = self.anchor_reference
        if anchor is None:
            return "NOT_PROVIDED", "No anchor reference supplied"
        if not computed_root:
            return "NOT_CHECKED", "Merkle root unavailable; anchor binding not checked"
        if anchor.get("merkle_root") != computed_root:
            return "INVALID", "Anchor Merkle root does not match the event collection"
        kind = anchor.get("anchor_type", anchor.get("provider", "unknown"))
        if kind in ("local", "local_file"):
            return "LOCAL_ONLY", "Local record matches root; NOT an external anchor"
        return "UNVERIFIED", f"Provider {kind!r}: external proof verification is not implemented"
    
    def _canonical_json(self, event: Dict[str, Any]) -> str:
        """
        Reproduce this PoC's JSON serialization (not full RFC 8785 JCS).
        
        Args:
            event: Event dictionary
            
        Returns:
            Canonical JSON string
        """
        # Extract core fields for hashing (exclude computed fields)
        core_fields = {
            "account_id": event.get("account_id"),
            "clock_sync": event.get("clock_sync"),
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "payload": self._sort_dict(event.get("payload", {})),
            "policy_id": event.get("policy_id"),
            "system_id": event.get("system_id"),
            "tier": event.get("tier"),
            "timestamp": event.get("timestamp"),
            "vcp_version": event.get("vcp_version"),
        }
        
        # Include prev_hash only if present
        if event.get("prev_hash"):
            core_fields["prev_hash"] = event["prev_hash"]
        
        return json.dumps(core_fields, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    
    def _sort_dict(self, d: Any) -> Any:
        """Recursively sort dictionary keys."""
        if isinstance(d, dict):
            return {k: self._sort_dict(v) for k, v in sorted(d.items())}
        elif isinstance(d, list):
            return [self._sort_dict(item) for item in d]
        return d
    
    def _compute_hash(self, event: Dict[str, Any]) -> str:
        """
        Compute SHA-256 hash of event.
        
        Args:
            event: Event dictionary
            
        Returns:
            Hash as hex string
        """
        canonical = self._canonical_json(event)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    
    def _leaf_hash(self, data_hash: bytes) -> bytes:
        """Compute leaf hash with RFC 6962 domain separation."""
        return hashlib.sha256(self.LEAF_PREFIX + data_hash).digest()
    
    def _internal_hash(self, left: bytes, right: bytes) -> bytes:
        """Compute internal node hash with RFC 6962 domain separation."""
        return hashlib.sha256(self.INTERNAL_PREFIX + left + right).digest()
    
    def _compute_merkle_root(self, hashes: List[bytes]) -> bytes:
        """
        Compute Merkle root from list of event hashes.
        
        Args:
            hashes: List of event hashes
            
        Returns:
            Merkle root hash
        """
        if not hashes:
            return b''
        
        # Convert to leaf hashes
        leaves = [self._leaf_hash(h) for h in hashes]
        
        # Build tree
        current_layer = leaves
        while len(current_layer) > 1:
            next_layer = []
            for i in range(0, len(current_layer), 2):
                left = current_layer[i]
                right = current_layer[i + 1] if i + 1 < len(current_layer) else left
                next_layer.append(self._internal_hash(left, right))
            current_layer = next_layer
        
        return current_layer[0]
    
    def verify_event(self, event: Dict[str, Any], prev_event: Optional[Dict[str, Any]] = None) -> VerificationResult:
        """
        Verify a single event.
        
        Args:
            event: Event to verify
            prev_event: Previous event (for prev_hash verification)
            
        Returns:
            VerificationResult
        """
        errors = []
        
        # 1. Verify event hash
        computed_hash = self._compute_hash(event)
        stored_hash = event.get("event_hash", "")
        hash_valid = computed_hash == stored_hash
        
        if not hash_valid:
            errors.append(f"Hash mismatch: computed={computed_hash[:16]}..., stored={stored_hash[:16]}...")
        
        # 2. Verify sequence (if merkle_index present)
        sequence_valid = True
        if prev_event and "merkle_index" in event and "merkle_index" in prev_event:
            expected_index = prev_event["merkle_index"] + 1
            if event["merkle_index"] != expected_index:
                sequence_valid = False
                errors.append(f"Sequence gap: expected index {expected_index}, got {event['merkle_index']}")
        
        # 3. Verify prev_hash (optional in v1.1)
        prev_hash_valid = True
        if event.get("prev_hash") and prev_event:
            expected_prev_hash = prev_event.get("event_hash", "")
            if event["prev_hash"] != expected_prev_hash:
                prev_hash_valid = False
                errors.append(f"PrevHash mismatch")
        
        return VerificationResult(
            event_id=event.get("event_id", "unknown"),
            valid=hash_valid and sequence_valid and prev_hash_valid,
            hash_valid=hash_valid,
            sequence_valid=sequence_valid,
            prev_hash_valid=prev_hash_valid,
            errors=errors
        )
    
    def verify_chain(self) -> Tuple[bool, List[VerificationResult]]:
        """
        Verify entire event chain.
        
        Returns:
            Tuple of (overall_valid, list of individual results)
        """
        results = []
        prev_event = None
        
        for event in self.events:
            result = self.verify_event(event, prev_event)
            results.append(result)
            prev_event = event
        
        overall_valid = bool(results) and all(r.valid for r in results)
        return overall_valid, results
    
    def verify_merkle_root(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Verify Merkle root against security object.
        
        Returns:
            Tuple of (valid, computed_root, expected_root)
        """
        if not self.security_object:
            return True, None, None
        
        # Compute Merkle root from events
        event_hashes = []
        for event in self.events:
            if event.get("event_hash"):
                event_hashes.append(bytes.fromhex(event["event_hash"]))
        
        if not event_hashes:
            return False, None, None
        
        computed_root = self._compute_merkle_root(event_hashes)
        computed_root_hex = computed_root.hex()
        
        expected_root = self.security_object.get("merkle_root", "")
        
        count_valid = self.security_object.get("event_count") == len(self.events)
        return computed_root_hex == expected_root and count_valid, computed_root_hex, expected_root
    
    def print_report(self, chain_valid: bool, results: List[VerificationResult], 
                     merkle_valid: bool, computed_root: Optional[str], expected_root: Optional[str],
                     integrity_only: bool = False):
        """Print verification report."""
        
        print("=" * 70)
        print("VCP v1.1 PoC Evidence Verification Report (NON-CERTIFIED)")
        print("=" * 70)
        
        # Summary
        valid_count = sum(1 for r in results if r.valid)
        invalid_count = len(results) - valid_count
        
        anchor_status, anchor_detail = self.assess_anchor(computed_root)
        integrity_valid = chain_valid and merkle_valid and anchor_status != "INVALID"
        status = "[INCOMPLETE] SILVER NOT ESTABLISHED" if integrity_valid else "[FAIL] INVALID EVIDENCE"
        
        print(f"\n[Verification Results]")
        print(f"  Overall Status: {status}")
        print(f"  Checked Internal Integrity: {'[PASS]' if integrity_valid else '[FAIL]'}")
        print(f"  Mode: {'integrity-only' if integrity_only else 'evidence assessment'}")
        print(f"  Total Events: {len(results)}")
        print(f"  Valid Events: {valid_count}")
        print(f"  Invalid Events: {invalid_count}")
        
        # Chain integrity
        print(f"\n[Chain Integrity]")
        sequence_valid = all(r.sequence_valid for r in results)
        prev_hash_valid = all(r.prev_hash_valid for r in results)
        
        print(f"  Sequence Continuity: {'[PASS]' if sequence_valid else '[FAIL]'}")
        print(f"  PrevHash Integrity: {'[PASS]' if prev_hash_valid else '[FAIL]'}")
        
        # Merkle root
        if computed_root:
            print(f"  Merkle Root and Event Count: {'[PASS]' if merkle_valid else '[FAIL]'}")
            print(f"  Computed Root: {computed_root}")
            if self.verbose:
                print(f"    Computed: {computed_root[:32]}...")
                if expected_root:
                    print(f"    Expected: {expected_root[:32]}...")
        else:
            print("  Merkle Root: [NOT CHECKED] No security object")

        print("\n[External Assurance]")
        print(f"  External Anchor: [{anchor_status}] {anchor_detail}")
        silver_status = "NOT MET" if anchor_status == "LOCAL_ONLY" else "NOT ESTABLISHED"
        print(f"  Silver External-Anchor Requirement: [{silver_status}]")
        print("  External Timestamp and 24-hour Cadence: [NOT VERIFIED]")
        print("  Digital Signatures and Signer Identity: [NOT VERIFIED]")
        print("  Full VCP Conformance and Collection Completeness: [NOT ASSESSED]")
        print("  Certification: NON-CERTIFIED PoC")
        
        # Invalid events details
        if invalid_count > 0:
            print(f"\n[Invalid Events]")
            for r in results:
                if not r.valid:
                    print(f"  - {r.event_id}: {', '.join(r.errors)}")
        
        print("=" * 70)
        if integrity_valid:
            print("Checked internal integrity passed; Silver compliance is NOT established.")
        else:
            print("Evidence integrity checks failed; Silver compliance is NOT established.")
        print("=" * 70)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="VCP v1.1 Event Chain Verifier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python vcp_verifier.py events.jsonl
  python vcp_verifier.py events.jsonl -s security_object.json
  python vcp_verifier.py events.jsonl -s security_object.json -v
        """
    )
    
    parser.add_argument("events_file", help="Path to events JSONL file")
    parser.add_argument("-s", "--security-object", help="Path to security object JSON")
    parser.add_argument("-a", "--anchor-reference", help="Path to anchor metadata JSON (not proof verification)")
    parser.add_argument("--integrity-only", action="store_true",
                        help="Allow exit 0 for checked internal integrity only; never certifies Silver")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    # Verify file exists
    if not Path(args.events_file).exists():
        print(f"Error: Events file not found: {args.events_file}")
        sys.exit(1)
    
    # Initialize verifier
    verifier = VCPVerifier(verbose=args.verbose)
    
    # Load events
    try:
        count = verifier.load_events(args.events_file)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    if count == 0:
        print("Error: No events loaded")
        sys.exit(1)
    
    print(f"Loaded {count} events from {args.events_file}")
    
    # Load security object if provided
    if args.security_object:
        if not verifier.load_security_object(args.security_object):
            sys.exit(1)
    if args.anchor_reference:
        try:
            verifier.load_anchor_reference(args.anchor_reference)
        except (OSError, ValueError) as exc:
            print(f"Error: {exc}")
            sys.exit(1)
    
    # Verify chain
    try:
        chain_valid, results = verifier.verify_chain()
        merkle_valid, computed_root, expected_root = verifier.verify_merkle_root()
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"Error: Invalid evidence structure: {exc}")
        sys.exit(1)
    
    # Print report
    verifier.print_report(chain_valid, results, merkle_valid, computed_root, expected_root,
                          integrity_only=args.integrity_only)
    
    # Exit code
    anchor_status, _ = verifier.assess_anchor(computed_root)
    if not chain_valid or not merkle_valid or anchor_status == "INVALID":
        sys.exit(1)
    sys.exit(0 if args.integrity_only else 2)


if __name__ == "__main__":
    main()
