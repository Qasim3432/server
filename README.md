# API Documentation

**API Version:** `v1`  
**Base URL:** `TBD`

---

## Table of Contents

- [Authentication](#authentication)
- [Deposit](#deposit)
- [User](#user)
- [Game](#game)
- [Wager](#wager)
- [Referral](#referral)
- [Withdrawal](#withdrawal)
- [WebSocket](#websocket)
- [Response Format](#response-format)
- [Game Status](#game-status)
- [Development Status](#development-status)

---

# Authentication

Authentication status varies by endpoint.

> `device_token` / `player_token` are currently used as client identifiers.
> Production authentication is pending implementation.

---

# Deposit

## Get Active Payment Methods

Returns all currently active deposit/payment methods.

### Request

```http
GET /api/deposit/methods/
