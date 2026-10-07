# VCP Webhook Payload Format

This document describes the JSON payload format for VCP TradingView webhooks.

## Overview

When TradingView triggers an alert, it sends a JSON payload to the configured webhook URL. The VCP Sidecar receives this payload and processes it according to VCP v1.1 specifications.

## Payload Structure

```json
{
  "vcp_version": "1.1",
  "event_id": "unique-event-identifier",
  "timestamp": "2025-01-15T10:30:00.123Z",
  "event_type": "ORDER_NEW",
  "tier": "SILVER",
  "policy_id": "urn:vso:policy:tv-retail:v1",
  "clock_sync": "BEST_EFFORT",
  "system_id": "TV-STRATEGY-001",
  "account_id": "DEMO-ACCOUNT",
  "payload": {
    // Event-specific data
  }
}
```

## Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `vcp_version` | string | Yes | VCP protocol version (e.g., "1.1") |
| `event_id` | string | Yes | Unique event identifier (UUID v7-like format) |
| `timestamp` | string | Yes | ISO 8601 timestamp with milliseconds (UTC) |
| `event_type` | string | Yes | Event type (see Event Types below) |
| `tier` | string | Yes | Declared target tier: "SILVER", "GOLD", or "PLATINUM"; not a compliance result |
| `policy_id` | string | Yes | Policy identifier (URN format) |
| `clock_sync` | string | Yes | Clock sync status: "BEST_EFFORT", "NTP_SYNCED", or "PTP_LOCKED" |
| `system_id` | string | Yes | Trading system identifier |
| `account_id` | string | Yes | Trading account identifier |
| `payload` | object | Yes | Event-specific payload data |

## Event Types

### ORDER_NEW

Triggered when a new order is placed.

```json
{
  "payload": {
    "order_id": "ORD-001",
    "symbol": "BTCUSD",
    "side": "BUY",
    "order_type": "MARKET",
    "quantity": 0.1,
    "price": 52000.00,
    "stop_loss": 50960.00,
    "take_profit": 54080.00,
    "algo_id": "MACD_CROSSOVER_V1",
    "decision_params": {
      "macd_line": -150.25,
      "signal_line": -175.50,
      "histogram": 25.25
    }
  }
}
```

### ORDER_FILLED

Triggered when an order is filled.

```json
{
  "payload": {
    "order_id": "ORD-001",
    "symbol": "BTCUSD",
    "side": "BUY",
    "fill_quantity": 0.1,
    "fill_price": 52005.50,
    "commission": 0.001,
    "realized_pnl": 0
  }
}
```

### POSITION_CLOSE

Triggered when a position is closed.

```json
{
  "payload": {
    "order_id": "ORD-002",
    "symbol": "BTCUSD",
    "side": "SELL",
    "close_quantity": 0.1,
    "close_price": 53250.00,
    "realized_pnl": 124.45,
    "close_reason": "SIGNAL_EXIT"
  }
}
```

### ALGO_PARAMETER_CHANGE

Triggered when algorithm parameters are changed.

```json
{
  "payload": {
    "algo_id": "MACD_CROSSOVER_V1",
    "parameter_name": "stop_loss_pct",
    "old_value": 2.0,
    "new_value": 2.5,
    "change_reason": "INCREASED_VOLATILITY"
  }
}
```

## TradingView Alert Setup

### Step 1: Create Alert

1. Open your strategy in TradingView
2. Click "Alert" button or press Alt+A
3. Configure alert conditions

### Step 2: Configure Webhook

1. In the alert dialog, check "Webhook URL"
2. Enter your VCP Sidecar URL: `https://your-server.com/vcp/event`
3. Set alert message to the JSON payload

### Step 3: Alert Message Template

Use this template for the alert message:

```
{{strategy.order.action}} signal generated

{"vcp_version":"1.1","event_id":"{{timenow}}-{{strategy.position_size}}","timestamp":"{{time}}","event_type":"ORDER_NEW","tier":"SILVER","policy_id":"urn:vso:policy:tv-retail:v1","clock_sync":"BEST_EFFORT","system_id":"{{ticker}}","account_id":"DEMO","payload":{"symbol":"{{ticker}}","side":"{{strategy.order.action}}","price":{{close}}}}
```

## Security Considerations

1. **Use HTTPS**: Always configure webhooks with HTTPS URLs
2. **Webhook Secret**: Configure webhook secret for payload validation
3. **IP Whitelisting**: Consider whitelisting TradingView IP ranges
4. **Rate Limiting**: Implement rate limiting to prevent abuse

## Error Handling

The VCP Sidecar returns standard HTTP status codes:

| Code | Description |
|------|-------------|
| 200 | Event processed successfully |
| 400 | Invalid payload format |
| 401 | Authentication failed |
| 429 | Rate limit exceeded |
| 500 | Internal server error |

## Response Format

Successful response:

```json
{
  "success": true,
  "event_id": "2025-0115-7103-0000-a1b2c3d4e5f",
  "event_hash": "a1b2c3d4...",
  "signature": "e5f6g7h8...",
  "merkle_index": 42,
  "message": "Event captured and signed successfully"
}
```

## VCP v1.1 PoC Scope and Design Targets

- **Policy Identification**: Required field `policy_id` identifies applicable policies
- **External Anchoring**: Silver requires a real external anchor every 24 hours. This PoC includes only local evidence and simulation stubs; the requirement is not met.
- **Merkle Tree**: Events are added to an RFC 6962 compliant Merkle tree
- **Ed25519 Signatures**: Each event is signed for integrity verification
