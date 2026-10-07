"""
VCP Sidecar Package
Non-certified PoC targeting VeritasChain Protocol v1.1 Silver Tier for TradingView

This package provides:
- FastAPI webhook receiver for TradingView alerts
- VCP event processing and canonical transformation
- Ed25519 digital signatures
- RFC 6962 Merkle tree construction
- Local anchoring and external-provider simulation stubs (no external assurance)

Copyright (c) 2025 VeritasChain Standards Organization
License: MIT
"""

__version__ = "1.0.0"
__vcp_version__ = "1.1"
__tier__ = "SILVER"

from .vcp_core import VCPEvent, VCPEventStore, VCPSigner, VCPEventType, VCPTier
from .merkle import MerkleTree
from .anchor import AnchorService, AnchorResult

__all__ = [
    "VCPEvent",
    "VCPEventStore", 
    "VCPSigner",
    "VCPEventType",
    "VCPTier",
    "MerkleTree",
    "AnchorService",
    "AnchorResult"
]
