# VCP TradingView Integration Guide

Setup guide for the non-certified TradingView PoC targeting VCP v1.1. The bundled pack has only a local anchor and does not establish Silver compliance. External providers are simulation stubs, not production integrations.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Architecture Overview](#architecture-overview)
3. [Setup Guide](#setup-guide)
4. [Pine Script Configuration](#pine-script-configuration)
5. [Sidecar Deployment](#sidecar-deployment)
6. [Verification & Testing](#verification--testing)
7. [Troubleshooting](#troubleshooting)
8. [Regulatory Compliance](#regulatory-compliance)

## Prerequisites

### TradingView Requirements

- TradingView Pro, Pro+, or Premium subscription (required for webhook alerts)
- Pine Script v5 knowledge
- Active strategy to monitor

### Server Requirements

- Python 3.9 or higher
- Public HTTPS endpoint (for receiving webhooks)
- Minimum 1GB RAM, 10GB storage
- Reliable internet connection

### Optional

- Docker and Docker Compose
- SSL certificate (Let's Encrypt recommended)
- Domain name

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          VCP TRADINGVIEW INTEGRATION                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  TRADINGVIEW                                                      │   │
│  │  ┌──────────────────────────────────────────────────────────┐    │   │
│  │  │  Pine Script Strategy                                     │    │   │
│  │  │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐  │    │   │
│  │  │  │ Trading    │  │ VCP Event  │  │ Webhook Trigger    │  │    │   │
│  │  │  │ Logic      │→ │ Formatter  │→ │ (JSON Payload)     │  │    │   │
│  │  │  └────────────┘  └────────────┘  └────────────────────┘  │    │   │
│  │  └──────────────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                          │                               │
│                                          │ HTTPS POST                    │
│                                          ▼                               │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  VCP SIDECAR (Python/FastAPI)                                     │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │   │
│  │  │ Webhook  │  │ Canonical│  │ Merkle   │  │ External         │  │   │
│  │  │ Receiver │→ │ + Hash   │→ │ Tree     │→ │ Anchor           │  │   │
│  │  │          │  │ + Sign   │  │ Builder  │  │ (24h batch)      │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘  │   │
│  │       ↓              ↓              ↓              ↓              │   │
│  │  ┌──────────────────────────────────────────────────────────┐    │   │
│  │  │                    Local Storage                          │    │   │
│  │  │  events.jsonl  │  anchors/  │  keys/  │  merkle/         │    │   │
│  │  └──────────────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                          │                               │
│                                          ▼                               │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  EXTERNAL ANCHOR                                                  │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │   │
│  │  │OpenTimestamps│  │   Bitcoin    │  │  RFC 3161    │            │   │
│  │  │  (Default)   │  │  OP_RETURN   │  │     TSA      │            │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘            │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Setup Guide

### Step 1: Clone Repository

```bash
git clone https://github.com/veritaschain/vcp-tradingview-rta-reference.git
cd vcp-tradingview-rta-reference
```

### Step 2: Install Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install requirements
pip install -r requirements.txt
```

### Step 3: Generate Keys

```bash
python -m sidecar.keygen
```

This generates:
- `./keys/ed25519_private.pem` - Keep this SECRET
- `./keys/ed25519_public.pem` - Can be shared for verification

### Step 4: Configure Sidecar

Edit `sidecar/config/settings.yaml`:

```yaml
vcp:
  tier: "SILVER"
  version: "1.1"
  policy_id: "urn:vso:policy:tv-retail:v1"

server:
  host: "0.0.0.0"
  port: 8080
  webhook_secret: ""  # Set VCP_WEBHOOK_SECRET in the environment
  allowed_origins: []  # Explicit browser origins only; no wildcard

anchor:
  provider: "opentimestamps"
  interval_hours: 24
```

The secret is required at startup. Set it once in your private deployment
environment and configure the same value at the sender:

```bash
export VCP_WEBHOOK_SECRET="$(openssl rand -hex 32)"
```

Every `/vcp/` request needs `X-VCP-Webhook-Secret`. Event POSTs may instead put
`webhook_secret` at the top level of the JSON body; the sidecar removes this
transport field before recording/signing. The bundled Pine script does not
insert it: use a private alert-template adaptation or an authenticated relay.
Do not put the secret in URLs or public scripts. An explicit empty environment
value overrides YAML and refuses startup. Browser access is opt-in via exact
`allowed_origins`; server-to-server requests do not require CORS.

### Step 5: Start Sidecar

```bash
python -m sidecar.main
```

Or with Docker:

```bash
cd examples
docker-compose up -d
```

### Step 6: Verify Server

```bash
curl http://localhost:8080/health
```

Expected response:
```json
{
  "status": "healthy",
  "vcp_version": "1.1",
  "tier": "SILVER",
  "signer_ready": true,
  "events_pending": 0
}
```

## Pine Script Configuration

### Step 1: Create New Strategy

1. Open TradingView
2. Click "Pine Editor"
3. Create new strategy

### Step 2: Add VCP Strategy Code

Copy the code from `tradingview/vcp_silver_strategy.pine` to your Pine Script editor.

### Step 3: Configure Strategy Settings

In the strategy settings:

| Setting | Recommended Value |
|---------|-------------------|
| System ID | Unique identifier for your system |
| Account ID | Your account identifier |
| Enable VCP Logging | ✓ (checked) |

### Step 4: Add to Chart

1. Click "Add to Chart"
2. Verify strategy appears on chart
3. Check VCP status indicator (top-right)

### Step 5: Create Alert

1. Click "Alert" or press Alt+A
2. Set condition to your strategy
3. Enable "Webhook URL"
4. Enter: `https://your-server.com/vcp/event`
5. Click "Create"

## Sidecar Deployment

### Option A: Direct Python

```bash
# Production mode
uvicorn sidecar.main:app --host 0.0.0.0 --port 8080 --workers 4
```

### Option B: Docker

```bash
cd examples
docker-compose up -d
```

### Option C: Systemd Service

Create `/etc/systemd/system/vcp-sidecar.service`:

```ini
[Unit]
Description=VCP TradingView Sidecar
After=network.target

[Service]
User=vcp
WorkingDirectory=/opt/vcp-tradingview
Environment=PATH=/opt/vcp-tradingview/venv/bin
ExecStart=/opt/vcp-tradingview/venv/bin/uvicorn sidecar.main:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable vcp-sidecar
sudo systemctl start vcp-sidecar
```

### HTTPS Configuration

Use Nginx as reverse proxy with Let's Encrypt:

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo certbot --nginx -d vcp.yourdomain.com
```

Nginx config (`/etc/nginx/sites-available/vcp`):

```nginx
server {
    listen 443 ssl;
    server_name vcp.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/vcp.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/vcp.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Verification & Testing

### Test Webhook Manually

```bash
curl -X POST http://localhost:8080/vcp/event \
  -H "Content-Type: application/json" \
  -H "X-VCP-Webhook-Secret: $VCP_WEBHOOK_SECRET" \
  -d '{
    "vcp_version": "1.1",
    "event_id": "TEST-001",
    "timestamp": "2025-01-15T10:30:00.000Z",
    "event_type": "ORDER_NEW",
    "tier": "SILVER",
    "policy_id": "urn:vso:policy:tv-retail:v1",
    "clock_sync": "BEST_EFFORT",
    "system_id": "TEST-SYSTEM",
    "account_id": "TEST-ACCOUNT",
    "payload": {"order_id": "ORD-001", "symbol": "BTCUSD", "side": "BUY"}
  }'
```

### Verify Event

```bash
curl -H "X-VCP-Webhook-Secret: $VCP_WEBHOOK_SECRET" http://localhost:8080/vcp/verify/TEST-001
```

### Check Merkle Proof

```bash
curl -H "X-VCP-Webhook-Secret: $VCP_WEBHOOK_SECRET" http://localhost:8080/vcp/proof/TEST-001
```

### Force Anchor (Testing Only)

```bash
curl -X POST -H "X-VCP-Webhook-Secret: $VCP_WEBHOOK_SECRET" http://localhost:8080/vcp/anchor/force
```

The forced and periodic paths share the same batch handling (corrected
2026-11-02):

- An attempt seals the oldest pending batch. New events enter a fresh tree
  while the provider call is awaiting a result; their returned indices are
  not rewritten or discarded.
- Provider `success=False`, an exception, cancellation, or a result for a
  different root leaves the sealed batch pending. Subsequent attempts retry
  that same root before newer events. Simultaneous anchor requests are
  serialized within this process.
- The forced endpoint returns HTTP **502** if the result is unconfirmed,
  **400** when no batch is pending, and **200** with `success: true` only when
  the provider explicitly reports success for the submitted root. This is
  the provider operation's result, not a Silver assessment or independent
  verification of external proof. Local-provider success is still local only.
- `/health` and `/vcp/anchor/status` include the sealed and active batches in
  their pending count. The status `merkle_root` is the oldest pending batch's
  root, not a root spanning the entire pending count.
- Proof lookup matches both the hash and batch-local index in pending trees.
  A retired/unavailable inclusion proof returns HTTP **409**; it is not
  generated from an unrelated later batch that reuses the same index.

The batching state is in memory in a single process. Restart recovery,
coordination between multiple workers, and a persistent archive of retired
inclusion proofs are not implemented. Run this PoC with one worker. The
bundled external providers remain simulation stubs and cannot drain a pending
batch successfully; these changes do not implement an external backend.

## Troubleshooting

### Webhook Not Received

1. Check TradingView alert is active
2. Verify webhook URL is correct
3. Check server logs: `docker-compose logs -f`
4. Ensure port is open: `sudo ufw allow 8080`

### Signature Verification Failed

1. Verify keys exist: `ls -la ./keys/`
2. Regenerate keys: `python -m sidecar.keygen`
3. Check key permissions: `chmod 600 ./keys/ed25519_private.pem`

### Anchor Failed

The bundled OpenTimestamps, Bitcoin and TSA providers deliberately return
failure because no external submission or verification is implemented.
HTTP 502 and retained pending events are the expected outcome with these
providers. Check the selected provider and logs; restoring network access
does not turn a simulation stub into an external anchor. A local provider is
available for local testing only.

### Pine Script Errors

1. Ensure Pine Script v5 (`//@version=5`)
2. Check JSON formatting in alert message
3. Verify webhook URL in alert settings

## Regulatory Compliance

### EU AI Act (Article 12)

Design targets only; these are not regulatory compliance findings for this PoC:
- ✅ Automatic event logging
- ✅ Timestamped records
- ✅ Tamper-evident storage
- **NOT IMPLEMENTED with real evidence:** External anchoring

### MiFID II (RTS 25)

VCP records include:
- ✅ Order identification
- ✅ Algorithm identification
- ✅ Decision parameters
- ✅ Timestamp with millisecond precision

### GDPR (VCP-PRIVACY)

For personal data:
- Configure VCP-PRIVACY module for crypto-shredding
- Implement data retention policies
- Enable "right to be forgotten" support

## Support

- **Documentation**: https://github.com/veritaschain/vcp-tradingview-rta-reference
- **Issues**: https://github.com/veritaschain/vcp-tradingview-rta-reference/issues
- **Email**: support@veritaschain.org
- **Standards**: standards@veritaschain.org

---

*VeritasChain Standards Organization - "Verify, Don't Trust"*
