
# Server Development

## Things Remaining to Work:
- [ ] **Production-Ready Authentication** - Secure token handling and encryption.
- [ ] **Profile Session Management** - Active session tracking and validation.
- [ ] **Anti-Bot System** - Rate-limiting and automated client detection.
- [ ] **Transaction ID System** - Unique tracking hashes for data logs.
- [ ] **AI / Computer Player** - Basic single-player bot logic.
- [ ] **Friends System** - Social networking, user lookups, and friend requests.
- [ ] **Room Creation** - Dynamic multiplayer lobbying and lobby logic.
- [ ] **Enhanced Referral System** - Invite mechanics with reward tracking.
- [ ] **Inter-User Chat** - Real-time websocket or polling communications.


# Api Documentation
- api/deposit/methods/
  - requires Get
  sends json
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

- initialize-game/
  -post rquires User, playermode
  {
    "player_token": "TEST_PLAYER_B",
    "is_two_player_mode": true
}

Respond

{
    "status": "success",
    "game_id": "58603452-c243-4086-9cc7-00c9585f1e50",
    "color": "GREEN",
    "game_status": "ACTIVE",
    "player_count": 1,
    "required_players": 2,
}

api/wager/join/

{
    "device_token": "TEST_PLAYER_003",
    "game_id": "2",
    "bet_amount": 500
}
  
