"""
VCP Core Module
VeritasChain Protocol v1.1 Core Implementation

Implements:
- VCPEvent: Event data model with canonical JSON serialization
- VCPSigner: Ed25519 digital signature
- VCPEventStore: Event persistence layer

Copyright (c) 2025 VeritasChain Standards Organization
License: MIT
"""

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Any, Dict

# Ed25519 signature support
try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("Warning: cryptography library not available. Using mock signer.")


# ============================================================================
# VCP Event Model
# ============================================================================

@dataclass
class VCPEvent:
    """
    VCP v1.1 Event Data Model
    
    Represents a single auditable event in the VeritasChain Protocol.
    Supports canonical JSON serialization per RFC 8785 (JCS).
    """
    
    # Core fields (required)
    event_id: str
    timestamp: str
    event_type: str
    tier: str
    policy_id: str
    clock_sync: str
    system_id: str
    account_id: str
    payload: Dict[str, Any]
    
    # VCP metadata
    vcp_version: str = "1.1"
    
    # Integrity fields (set after processing)
    event_hash: Optional[str] = None
    signature: Optional[str] = None
    merkle_index: Optional[int] = None
    prev_hash: Optional[str] = None  # OPTIONAL in v1.1
    
    # Timestamps
    received_at: Optional[str] = None
    
    def __post_init__(self):
        """Set received timestamp."""
        if not self.received_at:
            self.received_at = datetime.now(timezone.utc).isoformat()
    
    def to_canonical_json(self) -> str:
        """
        Convert event to canonical JSON format per RFC 8785 (JCS).
        
        Rules:
        1. Keys sorted lexicographically
        2. No whitespace
        3. Unicode escaped as \\uXXXX
        4. Numbers in minimal representation
        """
        # Build canonical structure (only include core fields)
        canonical = {
            "account_id": self.account_id,
            "clock_sync": self.clock_sync,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self._sort_dict(self.payload),
            "policy_id": self.policy_id,
            "system_id": self.system_id,
            "tier": self.tier,
            "timestamp": self.timestamp,
            "vcp_version": self.vcp_version,
        }
        
        # Include prev_hash only if present (OPTIONAL in v1.1)
        if self.prev_hash:
            canonical["prev_hash"] = self.prev_hash
        
        return json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    
    def _sort_dict(self, d: Any) -> Any:
        """Recursively sort dictionary keys for canonical form."""
        if isinstance(d, dict):
            return {k: self._sort_dict(v) for k, v in sorted(d.items())}
        elif isinstance(d, list):
            return [self._sort_dict(item) for item in d]
        else:
            return d
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VCPEvent':
        """Create event from dictionary."""
        return cls(**data)


# ============================================================================
# VCP Signer (Ed25519)
# ============================================================================

_ED25519_P = 2**255 - 19
# Five y coordinates cover all eight pure small-order points, both x signs.
_ED25519_SMALL_ORDER_Y = {
    0, 1, _ED25519_P - 1,
    int.from_bytes(bytes.fromhex(
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05"), "little"),
    int.from_bytes(bytes.fromhex(
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a"), "little"),
}


def _check_public_key(raw: bytes) -> None:
    """Apply local key admission; leave curve/equation and R/S checks to crypto.

    This rejects noncanonical and pure small-order keys, not mixed-order points.
    It is not an adopted VAP/VCP normative signature profile.
    """
    if len(raw) != 32:
        raise ValueError("Ed25519 public key must contain exactly 32 bytes")
    encoded = int.from_bytes(raw, "little")
    y = encoded & (2**255 - 1)
    if y >= _ED25519_P or (y in (1, _ED25519_P - 1) and encoded >> 255):
        raise ValueError("noncanonical Ed25519 public key encoding")
    if y in _ED25519_SMALL_ORDER_Y:
        raise ValueError("small-order Ed25519 public key")


class VCPSigner:
    """
    Ed25519 Digital Signature Implementation for VCP.
    
    Implements:
    - Key generation
    - Message signing
    - Signature verification
    - Key persistence
    """
    
    def __init__(self, private_key: Optional[Ed25519PrivateKey] = None, 
                 public_key: Optional[Ed25519PublicKey] = None):
        """Initialize signer with optional key pair."""
        self._private_key = private_key
        self._public_key = public_key or (private_key.public_key() if private_key else None)
        if self._public_key is not None:
            _check_public_key(self._public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ))
    
    @classmethod
    def generate(cls) -> 'VCPSigner':
        """Generate new Ed25519 key pair."""
        if not CRYPTO_AVAILABLE:
            return MockVCPSigner()
        
        private_key = Ed25519PrivateKey.generate()
        return cls(private_key=private_key)
    
    @classmethod
    def load_from_files(cls, private_key_path: str, public_key_path: str) -> 'VCPSigner':
        """Load key pair from PEM files."""
        if not CRYPTO_AVAILABLE:
            return MockVCPSigner()
        
        with open(private_key_path, 'rb') as f:
            private_key = serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
        
        with open(public_key_path, 'rb') as f:
            public_key = serialization.load_pem_public_key(
                f.read(), backend=default_backend()
            )
        
        return cls(private_key=private_key, public_key=public_key)
    
    def save_to_files(self, private_key_path: str, public_key_path: str):
        """Save key pair to PEM files."""
        if not CRYPTO_AVAILABLE or not self._private_key:
            raise RuntimeError("Cannot save keys: no private key available")
        
        # Ensure directory exists
        Path(private_key_path).parent.mkdir(parents=True, exist_ok=True)
        Path(public_key_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Save private key
        private_pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(private_key_path, 'wb') as f:
            f.write(private_pem)
        
        # Set restrictive permissions on private key
        os.chmod(private_key_path, 0o600)
        
        # Save public key
        public_pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with open(public_key_path, 'wb') as f:
            f.write(public_pem)
    
    def sign(self, message: bytes) -> bytes:
        """Sign a message with Ed25519 private key."""
        if not self._private_key:
            raise RuntimeError("No private key available for signing")
        
        return self._private_key.sign(message)
    
    def verify(self, message: bytes, signature: bytes) -> bool:
        """Verify Ed25519 signature."""
        if not self._public_key:
            raise RuntimeError("No public key available for verification")
        
        try:
            self._public_key.verify(signature, message)
            return True
        except Exception:
            return False
    
    def get_public_key_hex(self) -> str:
        """Get public key as hex string."""
        if not self._public_key:
            raise RuntimeError("No public key available")
        
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return public_bytes.hex()


class MockVCPSigner(VCPSigner):
    """Mock signer for when cryptography library is not available."""
    
    def __init__(self):
        super().__init__()
        self._mock_key = os.urandom(32)
    
    def sign(self, message: bytes) -> bytes:
        """Mock sign using HMAC-SHA256."""
        import hmac
        return hmac.new(self._mock_key, message, hashlib.sha256).digest()
    
    def verify(self, message: bytes, signature: bytes) -> bool:
        """Mock verify using HMAC-SHA256."""
        import hmac
        expected = hmac.new(self._mock_key, message, hashlib.sha256).digest()
        return hmac.compare_digest(signature, expected)
    
    def get_public_key_hex(self) -> str:
        """Return mock public key."""
        return hashlib.sha256(self._mock_key).hexdigest()
    
    def save_to_files(self, private_key_path: str, public_key_path: str):
        """Save mock keys."""
        Path(private_key_path).parent.mkdir(parents=True, exist_ok=True)
        with open(private_key_path, 'w') as f:
            f.write(f"MOCK_PRIVATE_KEY:{self._mock_key.hex()}")
        with open(public_key_path, 'w') as f:
            f.write(f"MOCK_PUBLIC_KEY:{hashlib.sha256(self._mock_key).hexdigest()}")


# ============================================================================
# VCP Event Store
# ============================================================================

class VCPEventStore:
    """
    Event persistence layer for VCP events.
    
    Supports:
    - File-based storage (JSON lines)
    - In-memory cache
    - Event retrieval and listing
    """
    
    def __init__(self, storage_path: str = "./data/events"):
        """Initialize event store."""
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self._events: Dict[str, VCPEvent] = {}
        self._event_file = self.storage_path / "events.jsonl"
        
        # Load existing events
        self._load_events()
    
    def _load_events(self):
        """Load events from persistent storage."""
        if self._event_file.exists():
            with open(self._event_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            event = VCPEvent.from_dict(data)
                            self._events[event.event_id] = event
                        except Exception as e:
                            print(f"Warning: Failed to load event: {e}")
    
    async def store(self, event: VCPEvent):
        """Store a VCP event."""
        self._events[event.event_id] = event
        
        # Append to file
        with open(self._event_file, 'a') as f:
            f.write(json.dumps(event.to_dict()) + '\n')
    
    async def get(self, event_id: str) -> Optional[VCPEvent]:
        """Retrieve an event by ID."""
        return self._events.get(event_id)
    
    async def list(self, limit: int = 100, offset: int = 0) -> List[VCPEvent]:
        """List events with pagination."""
        events = list(self._events.values())
        # Sort by timestamp descending
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[offset:offset + limit]
    
    async def count(self) -> int:
        """Get total event count."""
        return len(self._events)
    
    async def get_by_hash(self, event_hash: str) -> Optional[VCPEvent]:
        """Find event by hash."""
        for event in self._events.values():
            if event.event_hash == event_hash:
                return event
        return None


# ============================================================================
# Utility Functions
# ============================================================================

def generate_event_id() -> str:
    """Generate UUID v7-like event ID."""
    # UUID v7 format: timestamp-based with random suffix
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    random_part = uuid.uuid4().hex[:12]
    
    # Format as UUID-like string
    ts_hex = format(timestamp_ms, 'x').zfill(12)
    return f"{ts_hex[:8]}-{ts_hex[8:12]}-7{random_part[:3]}-{random_part[3:7]}-{random_part[7:12]}{uuid.uuid4().hex[:7]}"


def compute_event_hash(event: VCPEvent) -> bytes:
    """Compute SHA-256 hash of event."""
    canonical = event.to_canonical_json()
    return hashlib.sha256(canonical.encode('utf-8')).digest()


# ============================================================================
# VCP Event Types
# ============================================================================

class VCPEventType:
    """Standard VCP event types for trading systems."""
    
    # Order lifecycle
    ORDER_NEW = "ORDER_NEW"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_MODIFIED = "ORDER_MODIFIED"
    
    # Position lifecycle
    POSITION_OPEN = "POSITION_OPEN"
    POSITION_CLOSE = "POSITION_CLOSE"
    POSITION_MODIFIED = "POSITION_MODIFIED"
    
    # Algorithm events
    ALGO_SIGNAL = "ALGO_SIGNAL"
    ALGO_DECISION = "ALGO_DECISION"
    ALGO_PARAMETER_CHANGE = "ALGO_PARAMETER_CHANGE"
    
    # Risk events
    RISK_LIMIT_BREACH = "RISK_LIMIT_BREACH"
    RISK_PARAMETER_CHANGE = "RISK_PARAMETER_CHANGE"
    
    # System events
    SYSTEM_START = "SYSTEM_START"
    SYSTEM_STOP = "SYSTEM_STOP"
    SYSTEM_ERROR = "SYSTEM_ERROR"


# ============================================================================
# VCP Clock Sync Status
# ============================================================================

class VCPClockSync:
    """Clock synchronization status constants."""
    
    PTP_LOCKED = "PTP_LOCKED"      # Platinum tier
    NTP_SYNCED = "NTP_SYNCED"      # Gold tier
    BEST_EFFORT = "BEST_EFFORT"    # Silver tier
    UNRELIABLE = "UNRELIABLE"      # Degraded mode


# ============================================================================
# VCP Compliance Tier
# ============================================================================

class VCPTier:
    """VCP compliance tier constants."""
    
    PLATINUM = "PLATINUM"  # HFT/Exchange
    GOLD = "GOLD"          # Prop/Institutional
    SILVER = "SILVER"      # Retail/MT4/5
