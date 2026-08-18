# API Documentation

**API Version:** `v1`
**Base URL:** `TBD`

---

## Table of Contents

* [Authentication](#authentication)
* [Deposit](#deposit)
* [Game](#game)
* [Wager](#wager)
* [Withdrawal](#withdrawal)
* [WebSocket](#websocket)
* [Response Format](#response-format)
* [Error Handling](#error-handling)

---

# Authentication

Authentication status varies by endpoint.

> `player_token` and `device_token` are currently used by the application. Production authentication is pending implementation.

---

# Deposit

## Get Deposit Methods

Returns the currently configured deposit methods.

### Request

```http
GET /api/deposit/methods/
```

### Authentication

Required.

### Request Body

None.

### Response

**`200 OK`**

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

---

# Game

## Initialize Game

Creates a new game or assigns the player to an available waiting room.

### Request

```http
POST /initialize-game/
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

| Parameter            | Type    | Required |
| -------------------- | ------- | -------- |
| `player_token`       | string  | Yes      |
| `is_two_player_mode` | boolean | Yes      |

### Response

**`200 OK`**

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

### Response Parameters

| Parameter          | Type    | Description            |
| ------------------ | ------- | ---------------------- |
| `status`           | string  | Request status         |
| `game_id`          | string  | Unique game identifier |
| `color`            | string  | Assigned player color  |
| `game_status`      | string  | Current game status    |
| `player_count`     | integer | Current player count   |
| `required_players` | integer | Required players       |

---

# Wager

## Join Wager

Joins a player to the wager associated with a game.

### Request

```http
POST /api/wager/join/
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

| Parameter      | Type    | Required | Description              |
| -------------- | ------- | -------- | ------------------------ |
| `device_token` | string  | Yes      | Player/device identifier |
| `game_id`      | string  | Yes      | Game identifier          |
| `bet_amount`   | integer | Yes      | Wager amount             |

### Response

**`200 OK`**

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

### Response Parameters

| Parameter           | Type    | Description              |
| ------------------- | ------- | ------------------------ |
| `status`            | string  | Request status           |
| `message`           | string  | Operation result         |
| `game_id`           | string  | Associated game          |
| `game_status`       | string  | Current game status      |
| `coins`             | integer | Available player balance |
| `locked_coins`      | integer | Locked wager balance     |
| `bet_amount`        | integer | Game wager amount        |
| `total_pool_escrow` | integer | Total wager pool         |
| `service_fee_cut`   | integer | Platform fee             |
| `winner_payout`     | integer | Winner payout            |

### Errors

**Insufficient Balance**

```json
{
  "status": "error",
  "message": "Insufficient funds. Required: 500, Available: 200"
}
```

**Invalid Bet**

```json
{
  "status": "error",
  "message": "Invalid bet amount."
}
```

**Duplicate Player**

```json
{
  "status": "error",
  "message": "Player has already joined this game."
}
```

**Game Unavailable**

```json
{
  "status": "error",
  "message": "This game is no longer accepting players."
}
```

---

# Withdrawal

## Approve Withdrawal

Approves a pending withdrawal request.

### Request

```http
POST /api/withdrawal/{withdrawal_id}/approve/
```

### Path Parameters

| Parameter       | Type    | Required | Description           |
| --------------- | ------- | -------- | --------------------- |
| `withdrawal_id` | integer | Yes      | Withdrawal request ID |

### Response

**`200 OK`**

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

---

# WebSocket

## Ludo Game

### Endpoint

```text
/ws/ludo/{game_id}/?player_token={player_token}
```

### Parameters

| Parameter      | Type   | Required |
| -------------- | ------ | -------- |
| `game_id`      | string | Yes      |
| `player_token` | string | Yes      |

### Client Actions

#### Roll Dice

```json
{
  "action": "roll_dice"
}
```

#### Move Token

```json
{
  "action": "move_token",
  "token_id": 0,
  "color": "BLUE"
}
```

### Server Response

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

Successful responses use:

```json
{
  "status": "success"
}
```

Error responses use:

```json
{
  "status": "error",
  "message": "Error description."
}
```

---

# Game Status

| Status         | Description                       |
| -------------- | --------------------------------- |
| `LOBBY`        | Waiting for players               |
| `ACTIVE`       | Game in progress                  |
| `WON`          | Winner detected                   |
| `COMPLETED`    | Game and payout completed         |
| `CANCELLED`    | Game cancelled                    |
| `PAYOUT_ERROR` | Winner detected but payout failed |

---

# Wager Status

Wager state is represented through the associated `GameRoom`.

| State       | Description        |
| ----------- | ------------------ |
| `LOBBY`     | Accepting players  |
| `ACTIVE`    | Wager game started |
| `COMPLETED` | Wager settled      |
| `CANCELLED` | Wager refunded     |

---

# Development Status

| Component                 | Status      |
| ------------------------- | ----------- |
| Deposit Methods           | Implemented |
| Game Initialization       | Implemented |
| Wager Join                | Implemented |
| Wager Finalization        | Implemented |
| Wager Cancellation        | Implemented |
| Withdrawal Approval       | Implemented |
| Ludo WebSocket            | Implemented |
| Production Authentication | Planned     |
| Session Management        | Planned     |
| Anti-Bot Protection       | Planned     |
| Transaction ID System     | Planned     |
| AI Player                 | Planned     |
| Friends System            | Planned     |
| Enhanced Referral System  | Planned     |
| Inter-User Chat           | Planned     |
