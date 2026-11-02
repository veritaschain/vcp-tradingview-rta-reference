"""
VCP Sidecar for TradingView Integration
Non-certified PoC targeting VeritasChain Protocol v1.1 Silver Tier

Copyright (c) 2025 VeritasChain Standards Organization
License: MIT
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .vcp_core import VCPEvent, VCPEventStore, VCPSigner
from .merkle import MerkleTree
from .anchor import AnchorResult, AnchorService

# ============================================================================
# Configuration
# ============================================================================

CONFIG_PATH = Path(__file__).parent / "config" / "settings.yaml"

def load_config() -> dict:
    """Load configuration from YAML file."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            settings = yaml.safe_load(f)
    else:
        settings = {
            "vcp": {"tier": "SILVER", "version": "1.1", "policy_id": "urn:vso:policy:tv-retail:v1"},
            "server": {"host": "0.0.0.0", "port": 8080, "webhook_secret": "", "allowed_origins": []},
            "anchor": {"provider": "opentimestamps", "interval_hours": 24},
            "keys": {"private_key_path": "./keys/ed25519_private.pem", "public_key_path": "./keys/ed25519_public.pem"}
        }
    if not isinstance(settings, dict) or not isinstance(settings.get("server"), dict):
        raise ValueError("Configuration must contain a server mapping")
    if "VCP_WEBHOOK_SECRET" in os.environ:
        # An explicitly empty environment value must not fall back to a YAML key.
        settings["server"]["webhook_secret"] = os.environ["VCP_WEBHOOK_SECRET"]
    return settings

config = load_config()

# ============================================================================
# Logging Setup
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("vcp-sidecar")

# ============================================================================
# FastAPI Application
# ============================================================================

def create_app(settings: dict) -> FastAPI:
    application = FastAPI(
        title="VCP TradingView Sidecar",
        description="Non-certified VCP v1.1 PoC Sidecar for TradingView Integration",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
    )
    origins = settings["server"].get("allowed_origins", [])
    if not isinstance(origins, list):
        raise ValueError("server.allowed_origins must be an explicit list of origins")
    for origin in origins:
        if not isinstance(origin, str) or "*" in origin:
            raise ValueError("CORS origins must be explicit HTTP(S) origins without wildcards")
        parsed = urlsplit(origin)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.path
                or parsed.query or parsed.fragment or origin != origin.strip()):
            raise ValueError("CORS entries must be origins, without paths or credentials")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("CORS origin contains an invalid port") from exc
    if settings["server"].get("cors_enabled", True) and origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-VCP-Webhook-Secret"],
        )
    return application


app = create_app(config)


def configured_webhook_secret() -> bytes:
    secret = config.get("server", {}).get("webhook_secret")
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("Set a nonempty VCP_WEBHOOK_SECRET or server.webhook_secret before startup")
    return secret.encode("utf-8")


def authenticate_request(request: Request, body_secret: Optional[str] = None) -> None:
    """Check transport credentials before logging, signing, persistence or anchoring."""
    try:
        expected = configured_webhook_secret()
    except ValueError:
        raise HTTPException(status_code=503, detail="Webhook authentication is not configured")
    header_values = request.headers.getlist("x-vcp-webhook-secret")
    supplied = header_values + ([body_secret] if body_secret is not None else [])
    valid = bool(supplied) and len(header_values) <= 1
    for value in supplied:
        # Evaluate each provided credential; a conflicting header/body is rejected.
        valid = hmac.compare_digest(value.encode("utf-8"), expected) and valid
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid webhook credentials")

# ============================================================================
# Global State
# ============================================================================

event_store: Optional[VCPEventStore] = None
merkle_tree: Optional[MerkleTree] = None
signer: Optional[VCPSigner] = None
anchor_service: Optional[AnchorService] = None
# A sealed batch is never modified while its provider request is in flight.
# Failed/cancelled attempts keep this batch; new arrivals use merkle_tree.
_pending_anchor_tree: Optional[MerkleTree] = None
_anchor_lock = asyncio.Lock()


def pending_event_count() -> int:
    """Count both the sealed retry batch and the active arrival batch."""
    return ((merkle_tree.size if merkle_tree is not None else 0)
            + (_pending_anchor_tree.size if _pending_anchor_tree is not None else 0))


def next_anchor_tree() -> Optional[MerkleTree]:
    """The oldest pending batch is retried before newer arrivals."""
    return _pending_anchor_tree if _pending_anchor_tree is not None else merkle_tree


def event_pending_tree(leaf_index: int, event_hash: bytes) -> Optional[MerkleTree]:
    """Match the hash as well as the batch-local index before returning a proof."""
    for tree in (_pending_anchor_tree, merkle_tree):
        if tree is not None and tree.verify_inclusion(leaf_index, event_hash):
            return tree
    return None


async def anchor_pending_batch() -> Optional[tuple[bytes, AnchorResult]]:
    """Anchor one sealed batch without dropping arrivals or failed attempts.

    Only anchor attempts are serialized. The swap has no await point, so event
    handlers on this event loop always append to either the old or the new tree.
    Keeping the failed batch separate avoids rewriting already returned indices.
    This is in-memory, single-process bookkeeping, not crash recovery.
    """
    global merkle_tree, _pending_anchor_tree
    async with _anchor_lock:
        if merkle_tree is None or anchor_service is None:
            raise RuntimeError("Anchor components are not initialized")
        if _pending_anchor_tree is None:
            if merkle_tree.size == 0:
                return None
            next_tree = MerkleTree(hash_algo=merkle_tree.hash_algo)
            _pending_anchor_tree = merkle_tree
            merkle_tree = next_tree

        merkle_root = _pending_anchor_tree.get_root()
        result = await anchor_service.anchor(merkle_root)
        if result.success is not True or result.merkle_root != merkle_root.hex():
            raise RuntimeError("Provider did not confirm the requested Merkle root")

        # No await between confirming this result and retiring only its batch.
        # Exceptions and cancellation above leave the sealed batch available.
        _pending_anchor_tree = None
        return merkle_root, result

# ============================================================================
# Request/Response Models
# ============================================================================

class TradingViewWebhook(BaseModel):
    """TradingView webhook payload model."""
    webhook_secret: Optional[str] = Field(default=None, strict=True, exclude=True, repr=False,
                                          description="Transport credential; not part of the recorded VCP event")
    vcp_version: str = Field(..., description="VCP version (e.g., '1.1')")
    event_id: str = Field(..., description="Unique event identifier")
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    event_type: str = Field(..., description="Event type (ORDER_NEW, ORDER_FILLED, etc.)")
    tier: str = Field(default="SILVER", description="Declared VCP target tier, not a conformance result")
    policy_id: str = Field(..., description="Policy identifier")
    clock_sync: str = Field(default="BEST_EFFORT", description="Clock synchronization status")
    system_id: str = Field(..., description="Trading system identifier")
    account_id: str = Field(..., description="Trading account identifier")
    payload: dict = Field(..., description="Event-specific payload data")


class VCPEventResponse(BaseModel):
    """Response model for VCP event submission."""
    success: bool
    event_id: str
    event_hash: str
    signature: str
    merkle_index: int
    message: str


class VerifyResponse(BaseModel):
    """Response model for event verification."""
    valid: bool
    event_id: str
    event_hash: str
    signature_valid: bool
    merkle_proof_valid: bool
    anchor_status: Optional[str]


class AnchorStatusResponse(BaseModel):
    """Response model for anchor status."""
    last_anchor_time: Optional[str]
    next_anchor_time: Optional[str]
    pending_events: int
    merkle_root: Optional[str]
    anchor_provider: str


# ============================================================================
# Lifecycle Events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize VCP components on startup."""
    global event_store, merkle_tree, signer, anchor_service, _pending_anchor_tree, _anchor_lock
    configured_webhook_secret()
    
    logger.info("Initializing VCP Sidecar...")
    
    # Initialize event store
    event_store = VCPEventStore(storage_path="./data/events")
    
    # Initialize Merkle tree
    merkle_tree = MerkleTree()
    _pending_anchor_tree = None
    _anchor_lock = asyncio.Lock()
    
    # Initialize signer
    private_key_path = config["keys"]["private_key_path"]
    public_key_path = config["keys"]["public_key_path"]
    
    if Path(private_key_path).exists():
        signer = VCPSigner.load_from_files(private_key_path, public_key_path)
        logger.info("Loaded existing Ed25519 key pair")
    else:
        logger.warning("No key pair found. Generate keys using: python -m sidecar.keygen")
        signer = VCPSigner.generate()
        logger.info("Generated new Ed25519 key pair (not persisted)")
    
    # Initialize anchor service
    anchor_service = AnchorService(
        provider=config["anchor"]["provider"],
        interval_hours=config["anchor"]["interval_hours"]
    )
    
    # Start background anchor task
    asyncio.create_task(periodic_anchor())
    
    logger.info(f"VCP Sidecar started - Tier: {config['vcp']['tier']}, Version: {config['vcp']['version']}")


async def periodic_anchor():
    """Background task for periodic external anchoring."""
    interval_seconds = config["anchor"]["interval_hours"] * 3600
    
    while True:
        await asyncio.sleep(interval_seconds)
        
        try:
            anchored = await anchor_pending_batch()
            if anchored is not None:
                merkle_root, _ = anchored
                logger.info(f"Anchor provider confirmed Merkle root: {merkle_root.hex()}")
        except Exception:
            logger.error("Periodic anchor failed; pending batch retained for retry")


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "vcp_version": config["vcp"]["version"],
        "tier": config["vcp"]["tier"],
        "signer_ready": signer is not None,
        "events_pending": pending_event_count()
    }


@app.post("/vcp/event", response_model=VCPEventResponse)
async def receive_event(webhook: TradingViewWebhook, background_tasks: BackgroundTasks, request: Request):
    """
    Receive and process VCP event from TradingView webhook.
    
    This endpoint:
    1. Validates the incoming event
    2. Applies canonical transformation (JCS)
    3. Generates SHA-256 hash
    4. Signs with Ed25519
    5. Adds to Merkle tree
    """
    global event_store, merkle_tree, signer
    authenticate_request(request, webhook.webhook_secret)
    
    logger.info(f"Received event: {webhook.event_type} - {webhook.event_id}")
    
    try:
        # Create VCP event
        vcp_event = VCPEvent(
            event_id=webhook.event_id,
            timestamp=webhook.timestamp,
            event_type=webhook.event_type,
            tier=webhook.tier,
            policy_id=webhook.policy_id,
            clock_sync=webhook.clock_sync,
            system_id=webhook.system_id,
            account_id=webhook.account_id,
            payload=webhook.payload,
            vcp_version=webhook.vcp_version
        )
        
        # Canonical transformation and hash
        canonical_json = vcp_event.to_canonical_json()
        event_hash = hashlib.sha256(canonical_json.encode('utf-8')).digest()
        
        # Sign the hash
        signature = signer.sign(event_hash)
        
        # Add to Merkle tree
        merkle_index = merkle_tree.add_leaf(event_hash)
        
        # Store event
        vcp_event.event_hash = event_hash.hex()
        vcp_event.signature = signature.hex()
        vcp_event.merkle_index = merkle_index
        
        background_tasks.add_task(event_store.store, vcp_event)
        
        logger.info(f"Event processed: {webhook.event_id} - Hash: {event_hash.hex()[:16]}...")
        
        return VCPEventResponse(
            success=True,
            event_id=webhook.event_id,
            event_hash=event_hash.hex(),
            signature=signature.hex(),
            merkle_index=merkle_index,
            message="Event captured and signed successfully"
        )
        
    except Exception as e:
        logger.error(f"Event processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/vcp/verify/{event_id}", response_model=VerifyResponse)
async def verify_event(event_id: str, request: Request):
    """
    Verify the integrity of a stored VCP event.
    
    Checks:
    1. Event hash validity
    2. Signature validity
    3. Merkle proof validity
    4. Anchor status (if available)
    """
    global event_store, signer
    authenticate_request(request)
    
    try:
        # Retrieve event
        vcp_event = await event_store.get(event_id)
        
        if not vcp_event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Verify hash
        canonical_json = vcp_event.to_canonical_json()
        computed_hash = hashlib.sha256(canonical_json.encode('utf-8')).digest()
        hash_valid = computed_hash.hex() == vcp_event.event_hash
        
        # Verify signature
        signature_valid = signer.verify(
            bytes.fromhex(vcp_event.event_hash),
            bytes.fromhex(vcp_event.signature)
        )
        
        # Verify Merkle proof
        merkle_proof_valid = (
            vcp_event.merkle_index is not None
            and event_pending_tree(vcp_event.merkle_index, computed_hash) is not None
        )
        
        # Check anchor status
        anchor_status = await anchor_service.get_status(vcp_event.merkle_index)
        
        return VerifyResponse(
            valid=hash_valid and signature_valid,
            event_id=event_id,
            event_hash=vcp_event.event_hash,
            signature_valid=signature_valid,
            merkle_proof_valid=merkle_proof_valid,
            anchor_status=anchor_status
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/vcp/proof/{event_id}")
async def get_merkle_proof(event_id: str, request: Request):
    """
    Get Merkle inclusion proof for an event.
    
    Returns:
    - Merkle path (audit trail)
    - Merkle root
    - Anchor proof (if available)
    """
    global event_store, merkle_tree
    authenticate_request(request)
    
    try:
        vcp_event = await event_store.get(event_id)
        
        if not vcp_event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        if vcp_event.merkle_index is None:
            raise HTTPException(status_code=400, detail="Event not in Merkle tree")
        
        # Batch-local indices can repeat after a swap: also match the event hash.
        tree = event_pending_tree(vcp_event.merkle_index, bytes.fromhex(vcp_event.event_hash))
        if tree is None:
            raise HTTPException(status_code=409, detail="Event proof is not available in a pending batch")
        proof = tree.get_proof(vcp_event.merkle_index)
        
        return {
            "event_id": event_id,
            "event_hash": vcp_event.event_hash,
            "merkle_index": vcp_event.merkle_index,
            "merkle_root": tree.get_root().hex(),
            "proof": [{"position": p[0], "hash": p[1].hex()} for p in proof],
            "anchor_proof": await anchor_service.get_proof(vcp_event.merkle_index)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Proof generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/vcp/anchor/status", response_model=AnchorStatusResponse)
async def get_anchor_status(request: Request):
    """Get current anchoring status."""
    global merkle_tree, anchor_service
    authenticate_request(request)
    tree = next_anchor_tree()
    
    return AnchorStatusResponse(
        last_anchor_time=anchor_service.last_anchor_time.isoformat() if anchor_service.last_anchor_time else None,
        next_anchor_time=anchor_service.next_anchor_time.isoformat() if anchor_service.next_anchor_time else None,
        pending_events=pending_event_count(),
        merkle_root=tree.get_root().hex() if tree is not None and tree.size > 0 else None,
        anchor_provider=config["anchor"]["provider"]
    )


@app.post("/vcp/anchor/force")
async def force_anchor(request: Request):
    """Force immediate anchoring (for testing/emergency use)."""
    global merkle_tree, anchor_service
    authenticate_request(request)
    
    try:
        anchored = await anchor_pending_batch()
    except Exception:
        logger.error("Forced anchor failed; pending batch retained for retry")
        raise HTTPException(status_code=502, detail="Anchor not confirmed; pending batch retained for retry")
    if anchored is None:
        raise HTTPException(status_code=400, detail="No events to anchor")
    merkle_root, result = anchored
    return {
        "success": True,
        "merkle_root": merkle_root.hex(),
        "anchor_result": result
    }


@app.get("/vcp/events")
async def list_events(request: Request, limit: int = 100, offset: int = 0):
    """List stored VCP events with pagination."""
    global event_store
    authenticate_request(request)
    
    events = await event_store.list(limit=limit, offset=offset)
    
    return {
        "total": await event_store.count(),
        "limit": limit,
        "offset": offset,
        "events": [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "timestamp": e.timestamp,
                "event_hash": e.event_hash[:16] + "..." if e.event_hash else None,
                "merkle_index": e.merkle_index
            }
            for e in events
        ]
    }


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Run the VCP Sidecar server."""
    uvicorn.run(
        "sidecar.main:app",
        host=config["server"]["host"],
        port=config["server"]["port"],
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    main()
