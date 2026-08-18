# API Documentation

**API Version:** `v1`  
**Base URL:** `TBD`

---

## Table of Contents

- [Authentication](#authentication)
- [User](#user)
  - [Create Test User](#create-test-user)
  - [Get User Balance](#get-user-balance)
  - [Get Transaction History](#get-transaction-history)
- [Deposit](#deposit)
  - [Get Active Payment Methods](#get-active-payment-methods)
- [Game](#game)
  - [Initialize Game](#initialize-game)
- [Wager](#wager)
  - [Join Wager](#join-wager)
- [Referral](#referral)
  - [Get Referral Code](#get-referral-code)
  - [Apply Referral Code](#apply-referral-code)
- [Withdrawal](#withdrawal)
  - [Approve Withdrawal](#approve-withdrawal)
- [WebSocket](#websocket)
  - [Ludo Game](#ludo-game)
- [Response Format](#response-format)
- [Game Status](#game-status)
- [Development Status](#development-status)

---

# Authentication

Production authentication is not yet implemented.

The current API uses:

- `device_token`
- `player_token`

as client/player identifiers.

> Production-ready authentication and secure token handling are planned.

---

# User

## Create Test User

Development/testing endpoint for creating or updating a `UserProfileBalance`.

This endpoint is available only when Django `DEBUG=True`.

### Endpoint

```http
POST /TBD/
```

### Headers

```http
Content-Type: application/json
```

### Request Body

```json
{
  "device_token": "TEST_PLAYER_001",
  "nickname": "Test Player",
  "phone_number": "03001234567"
}
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `device_token` | string | Yes | Unique device identifier |
| `nickname` | string | No | User display name |
| `phone_number` | string | Yes | User phone number |

### Success Response

#### New User

**HTTP `201 Created`**

```json
{
  "status": "success",
  "created": true,
  "user": {
    "device_token": "TEST_PLAYER_001",
    "nickname": "Test Player",
    "phone_number": "03001234567",
    "coins": 0,
    "locked_coins": 0,
    "referral_code": "ABC123"
  }
}
```

#### Existing User

**HTTP `200 OK`**

```json
{
  "status": "success",
  "created": false,
  "user": {
    "device_token": "TEST_PLAYER_001",
    "nickname": "Test Player",
    "phone_number": "03001234567",
    "coins": 0,
    "locked_coins": 0,
    "referral_code": "ABC123"
  }
}
```

### Errors

#### Invalid HTTP Method

**HTTP `405 Method Not Allowed`**

```json
{
  "status": "error",
  "message": "POST required."
}
```

#### Test User Creation Disabled

**HTTP `403 Forbidden`**

```json
{
  "status": "error",
  "message": "Test user creation is disabled."
}
```

#### Missing Device Token

**HTTP `400 Bad Request`**

```json
{
  "status": "error",
  "message": "device_token is required."
}
```

#### Missing Phone Number

**HTTP `400 Bad Request`**

```json
{
  "status": "error",
  "message": "phone_number is required."
}
```

#### Phone Number Already Registered

**HTTP `409 Conflict`**

```json
{
  "status": "error",
  "message": "This phone number is already registered.",
  "existing_device_token": "TEST_PLAYER_002"
}
```

---

## Get User Balance

Returns the user's current available coin balance.

### Endpoint

```http
GET /TBD/{device_token}/
```

### Path Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `device_token` | string | Yes | User device identifier |

### Success Response

**HTTP `200 OK`**

```json
{
  "status": "success",
  "coins": 1500
}
```

---

## Get Transaction History

Returns combined deposit and withdrawal history for the specified user.

### Endpoint

```http
GET /TBD/{device_token}/
```

### Path Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `device_token` | string | Yes | User device identifier |

### Success Response

**HTTP `200 OK`**

```json
{
  "status": "success",
  "transactions": [
    {
      "type": "DEPOSIT",
      "amount": 1000,
      "status": "APPROVED",
      "date": "19 Aug 2026, 02:30 PM"
    },
    {
      "type": "WITHDRAWAL",
      "amount": 500,
      "status": "PENDING",
      "date": "18 Aug 2026, 11:15 AM"
    }
  ]
}
```

### Transaction Types

| Type | Description |
|---|---|
| `DEPOSIT` | Deposit transaction |
| `WITHDRAWAL` | Withdrawal transaction |

---

# Deposit

## Get Active Payment Methods

Returns all currently active payment/deposit methods.

### Endpoint

```http
GET /api/deposit/methods/
```

### Request Body

None.

### Success Response

**HTTP `200 OK`**

```json
{
  "status": "success",
  "methods": {
    "EASYPAISA": {
      "name": "Hello",
      "number": "0232234"
    },
    "JAZZCASH": {
      "name": "pp",
      "number": "44565645"
    },
    "BINANCE": {
      "name": "james",
      "number": "3332206556"
    }
  }
}
```

### Response Fields

| Field | Type | Description |
|---|---|---|
| `status` | string | Request status |
| `methods` | object | Active payment methods |
| `methods.*.name` | string | Account holder name |
| `methods.*.number` | string | Payment account number |

---

# Game

## Initialize Game

Finds an existing waiting room or creates a new game room.

The endpoint assigns a player to a game and assigns a color.

### Endpoint

```http
POST /initialize-game/
```

### Headers

```http
Content-Type: application/json
```

### Request Body

```json
{
  "player_token": "TEST_PLAYER_B",
  "is_two_player_mode": true
}
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `player_token` | string | Yes | Player identifier |
| `is_two_player_mode` | boolean | Yes | `true` for 2-player mode, `false` for 4-player mode |

### Success Response

**HTTP `200 OK`**

```json
{
  "status": "success",
  "game_id": "58603452-c243-4086-9cc7-00c9585f1e50",
  "color": "GREEN",
  "game_status": "ACTIVE",
  "player_count": 1,
  "required_players": 2
}
```

### Response Fields

| Field | Type | Description |
|---|---|---|
| `status` | string | Request status |
| `game_id` | string | Unique game identifier |
| `color` | string | Player's assigned color |
| `game_status` | string | Current game status |
| `player_count` | integer | Number of players currently assigned |
| `required_players` | integer | Number of players required |

### Supported Colors

#### 2 Player

```text
BLUE
GREEN
```

#### 4 Player

```text
BLUE
RED
GREEN
YELLOW
```

---

# Wager

## Join Wager

Adds a player to the wager associated with a game.

The wager is associated with the supplied `game_id`.

The player's wager amount is deducted from available coins and moved to `locked_coins`.

### Endpoint

```http
POST /api/wager/join/
```

### Headers

```http
Content-Type: application/json
```

### Request Body

```json
{
  "device_token": "TEST_PLAYER_003",
  "game_id": "58603452-c243-4086-9cc7-00c9585f1e50",
  "bet_amount": 500
}
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `device_token` | string | Yes | Player/device identifier |
| `game_id` | string | Yes | Game identifier |
| `bet_amount` | integer | Yes | Wager amount |

### Success Response

**HTTP `200 OK`**

```json
{
  "status": "success",
  "message": "Entry fee locked successfully.",
  "game_id": "58603452-c243-4086-9cc7-00c9585f1e50",
  "game_status": "LOBBY",
  "coins": 1500,
  "locked_coins": 500,
  "bet_amount": 500,
  "total_pool_escrow": 500,
  "service_fee_cut": 0,
  "winner_payout": 0
}
```

### Response Fields

| Field | Type | Description |
|---|---|---|
| `status` | string | Request status |
| `message` | string | Operation result |
| `game_id` | string | Associated game identifier |
| `game_status` | string | Current wager/game status |
| `coins` | integer | Available coins after wager |
| `locked_coins` | integer | Locked coins |
| `bet_amount` | integer | Required wager |
| `total_pool_escrow` | integer | Total wager pool |
| `service_fee_cut` | integer | Platform fee |
| `winner_payout` | integer | Winner payout |

### Errors

#### Invalid Bet Amount

**HTTP `200 OK`**

```json
{
  "status": "error",
  "message": "Invalid bet amount."
}
```

#### Bet Amount Is Zero or Negative

```json
{
  "status": "error",
  "message": "Bet amount must be greater than zero."
}
```

#### Insufficient Funds

```json
{
  "status": "error",
  "message": "Insufficient funds. Required: 500, Available: 200"
}
```

#### Game ID Missing

```json
{
  "status": "error",
  "message": "Game ID is required."
}
```

#### Game Not Found / Wallet Profile Missing

```json
{
  "status": "error",
  "message": "User wallet profile not found."
}
```

#### Incorrect Bet Amount

```json
{
  "status": "error",
  "message": "Incorrect bet amount. This room requires 500 coins."
}
```

#### Duplicate Player

```json
{
  "status": "error",
  "message": "Player has already joined this game."
}
```

#### Game Full

```json
{
  "status": "error",
  "message": "This game already has enough players."
}
```

#### Game No Longer Accepting Players

```json
{
  "status": "error",
  "message": "This game is no longer accepting players."
}
```

---

# Referral

## Get Referral Code

Returns the referral code assigned to a user.

### Endpoint

```http
GET /TBD/{device_token}/
```

### Path Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `device_token` | string | Yes | User device identifier |

### Success Response

**HTTP `200 OK`**

```json
{
  "status": "success",
  "referral_code": "ABC123"
}
```

---

## Apply Referral Code

Associates the current user with a referrer and awards the configured signup bonus.

### Endpoint

```http
POST /TBD/
```

### Headers

```http
Content-Type: application/json
```

### Request Body

```json
{
  "device_token": "TEST_PLAYER_002",
  "referral_code": "ABC123"
}
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `device_token` | string | Yes | Referred user device identifier |
| `referral_code` | string | Yes | Referrer's referral code |

### Success Response

**HTTP `200 OK`**

```json
{
  "status": "success",
  "message": "Referral applied successfully."
}
```

### Current Signup Bonus

```text
50 coins
```

The current implementation credits the bonus to:

1. The referred user
2. The referrer

### Errors

#### Invalid Method

**HTTP `405 Method Not Allowed`**

```json
{
  "status": "error",
  "message": "POST required."
}
```

#### Missing Parameters

**HTTP `400 Bad Request`**

```json
{
  "status": "error",
  "message": "Field verification failure! device_token and referral_code are required."
}
```

#### Referral Already Applied

**HTTP `400 Bad Request`**

```json
{
  "status": "error",
  "message": "Referral milestone already claimed on this device."
}
```

#### Self Referral

**HTTP `400 Bad Request`**

```json
{
  "status": "error",
  "message": "Self-referral operation is invalid."
}
```

#### Invalid Referral Code

**HTTP `400 Bad Request`**

```json
{
  "status": "error",
  "message": "The referral code \"INVALID\" does not exist in the database."
}
```

---

# Withdrawal

## Approve Withdrawal

Approves a pending withdrawal request.

The requested amount is deducted from the user's available balance.

If applicable, the configured referral commission is credited to the referrer.

### Endpoint

```http
POST /TBD/{withdrawal_id}/
```

### Path Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `withdrawal_id` | integer | Yes | Withdrawal request ID |

### Success Response

**HTTP `200 OK`**

```json
{
  "status": "success",
  "message": "Withdrawal approved successfully.",
  "withdrawal_id": 123,
  "device_token": "TEST_PLAYER_003",
  "amount": 500,
  "commission": 25,
  "remaining_balance": 1500
}
```

### Response Fields

| Field | Type | Description |
|---|---|---|
| `status` | string | Request status |
| `message` | string | Operation result |
| `withdrawal_id` | integer | Withdrawal request ID |
| `device_token` | string | User device identifier |
| `amount` | integer | Approved withdrawal amount |
| `commission` | integer | Referral commission |
| `remaining_balance` | integer | User balance after deduction |

---

# WebSocket

## Ludo Game

Establishes a real-time connection for a specific game.

### Endpoint

```text
/ws/ludo/{game_id}/?player_token={player_token}
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `game_id` | string | Yes | Game identifier |
| `player_token` | string | Yes | Player identifier |

---

## Roll Dice

### Client Message

```json
{
  "action": "roll_dice"
}
```

### Server State

The server updates:

```json
{
  "current_dice_value": 6,
  "has_rolled": true
}
```

---

## Move Token

### Client Message

```json
{
  "action": "move_token",
  "token_id": 0,
  "color": "BLUE"
}
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `action` | string | Yes | Must be `move_token` |
| `token_id` | integer | Yes | Token identifier |
| `color` | string | Yes | Player/token color |

---

## WebSocket Server Response

```json
{
  "status": "success",
  "game_state": {
    "game_status": "ACTIVE",
    "turn_index": 0,
    "current_dice_value": 6,
    "has_rolled": true,
    "player_turn_order": [
      "BLUE",
      "GREEN"
    ],
    "player_assignments": {
      "TEST_PLAYER_A": "BLUE",
      "TEST_PLAYER_B": "GREEN"
    },
    "tokens": []
  }
}
```

---

# Response Format

## Successful Response

```json
{
  "status": "success"
}
```

Additional response fields depend on the endpoint.

---

## Error Response

```json
{
  "status": "error",
  "message": "Error description."
}
```

---

# Game Status

| Status | Description |
|---|---|
| `LOBBY` | Game is waiting for players |
| `ACTIVE` | Game is currently in progress |
| `WON` | Winner has been detected |
| `COMPLETED` | Game and wager payout completed |
| `CANCELLED` | Game has been cancelled |
| `PAYOUT_ERROR` | Winner detected but payout processing failed |

---

# Wager Status

Wager state is associated with the corresponding `GameRoom`.

| Status | Description |
|---|---|
| `LOBBY` | Wager is accepting players |
| `ACTIVE` | Wager game has started |
| `COMPLETED` | Wager has been settled |
| `CANCELLED` | Wager has been cancelled and refunded |

---

# Development Status

| Component | Status |
|---|---|
| Deposit Methods | Implemented |
| Test User Creation | Implemented |
| User Balance | Implemented |
| Transaction History | Implemented |
| Game Initialization | Implemented |
| Wager Join | Implemented |
| Wager Finalization | Implemented |
| Wager Cancellation | Implemented |
| Withdrawal Approval | Implemented |
| Referral Code | Implemented |
| Referral Application | Implemented |
| Ludo WebSocket | Implemented |
| Production Authentication | Planned |
| Profile Session Management | Planned |
| Anti-Bot System | Planned |
| Transaction ID System | Planned |
| AI / Computer Player | Planned |
| Friends System | Planned |
| Enhanced Referral System | Planned |
| Inter-User Chat | Planned |
| Dynamic Room Creation | Implemented |
