# myapp/services/game_state_store.py

import json
import time
import uuid
from contextlib import contextmanager
from django.conf import settings
import redis

_client = None

def _get_redis():
    global _client
    if _client is None:
        _client = redis.Redis(
            host=getattr(settings, "GAME_REDIS_HOST", "127.0.0.1"),
            port=getattr(settings, "GAME_REDIS_PORT", 6379),
            db=getattr(settings, "GAME_REDIS_DB", 2),
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _client

STATE_PREFIX = "ludo:game:state:"
LOCK_PREFIX = "ludo:game:lock:"
TURN_DEADLINE_PREFIX = "ludo:turn_deadline:"
SURRENDER_DEADLINE_PREFIX = "ludo:surrender_deadline:"
WAITING_PREFIX = "ludo:waiting"           # ✅ NEW — matchmaking index
PLAYER_LOBBY_PREFIX = "ludo:player_lobby:" # ✅ NEW — player's current lobby
TTL_SECONDS = 60 * 60 * 6

def state_key(game_id): return f"{STATE_PREFIX}{game_id}"
def lock_key(game_id): return f"{LOCK_PREFIX}{game_id}"
def turn_deadline_key(game_id): return f"{TURN_DEADLINE_PREFIX}{game_id}"
def surrender_deadline_key(game_id, token): return f"{SURRENDER_DEADLINE_PREFIX}{game_id}:{token}"

class LockTimeout(Exception): pass

@contextmanager
def game_lock(game_id, lock_ttl=15, wait_timeout=5):
    r = _get_redis()
    key = lock_key(game_id)
    token = uuid.uuid4().hex
    deadline = time.time() + wait_timeout
    acquired = False
    while time.time() < deadline:
        if r.set(key, token, nx=True, ex=lock_ttl):
            acquired = True
            break
        time.sleep(0.02)
    if not acquired:
        raise LockTimeout(f"Could not acquire lock for game {game_id}")
    try:
        yield
    finally:
        if r.get(key) == token:
            r.delete(key)

def get_state(game_id):
    raw = _get_redis().get(state_key(str(game_id)))
    return json.loads(raw) if raw else None

def set_state(game_id, state):
    _get_redis().set(state_key(str(game_id)), json.dumps(state), ex=TTL_SECONDS)

def delete_state(game_id):
    return _get_redis().delete(state_key(str(game_id))) > 0

def exists(game_id):
    return _get_redis().exists(state_key(str(game_id))) > 0

def iter_all_game_ids():
    for key in _get_redis().scan_iter(f"{STATE_PREFIX}*"):
        yield key[len(STATE_PREFIX):]

def iter_all_states():
    for gid in iter_all_game_ids():
        s = get_state(gid)
        if s is not None:
            yield gid, s

class _GameStoreProxy:
    def get(self, game_id, default=None): return get_state(game_id) or default
    def __contains__(self, game_id): return exists(game_id)
    def __getitem__(self, game_id): 
        s = get_state(game_id)
        if s is None: raise KeyError(game_id)
        return s
    def __setitem__(self, game_id, state): set_state(game_id, state)
    def __delitem__(self, game_id):
        if not delete_state(game_id): raise KeyError(game_id)
    def pop(self, game_id, default=None):
        s = get_state(game_id)
        if s is not None: delete_state(game_id)
        return s or default
    def keys(self): return list(iter_all_game_ids())

ACTIVE_GAMES = _GameStoreProxy()

def mutate_game(game_id, mutate_fn):
    with game_lock(game_id):
        state = get_state(game_id)
        if state is None: return None
        result = mutate_fn(state)
        set_state(game_id, state)
        return result

def set_turn_deadline(game_id, turn_index, timeout_seconds):
    _get_redis().set(turn_deadline_key(game_id), str(turn_index), ex=timeout_seconds)

def clear_turn_deadline(game_id):
    _get_redis().delete(turn_deadline_key(game_id))

def get_turn_deadline(game_id):
    val = _get_redis().get(turn_deadline_key(game_id))
    return int(val) if val is not None else None

def set_surrender_deadline(game_id, player_token, grace_seconds):
    _get_redis().set(surrender_deadline_key(game_id, player_token), "1", ex=grace_seconds)

def clear_surrender_deadline(game_id, player_token):
    _get_redis().delete(surrender_deadline_key(game_id, player_token))

def iter_expired_surrenders():
    r = _get_redis()
    for game_id in iter_all_game_ids():
        state = get_state(game_id)
        if not state: continue
        for token in list(state.get("player_assignments", {}).keys()):
            if r.get(surrender_deadline_key(game_id, token)) is None:
                away_marker = f"ludo:away:{game_id}:{token}"
                if r.get(away_marker) is not None:
                    r.delete(away_marker)
                    yield game_id, token

def mark_player_away(game_id, player_token):
    _get_redis().set(f"ludo:away:{game_id}:{player_token}", "1", ex=3600)

def mark_player_back(game_id, player_token):
    _get_redis().delete(f"ludo:away:{game_id}:{player_token}")
    clear_surrender_deadline(game_id, player_token)


# ==========================================================
# ✅ NEW: WAITING ROOM INDEX
#
# Problem (issue #19):
#   `find_waiting_room` used `iter_all_states()` — O(N) where N =
#   ALL active game states. On every matchmaking attempt (6 retries
#   × 0.9s), it scanned the entire Redis namespace. At scale this
#   blocked workers.
#
# Fix:
#   Sorted SET `ludo:waiting:{mode}:{bet}` holds game_ids of
#   lobbies waiting for opponents. Lookup is O(M) where M =
#   waiting lobbies matching mode+bet (usually 0-3).
# ==========================================================

def waiting_set_key(is_two_player, bet_amount):
    mode = "2p" if is_two_player else "4p"
    return f"{WAITING_PREFIX}:{mode}:{int(bet_amount)}"


def add_waiting_room(game_id, is_two_player, bet_amount):
    """Add game_id to the waiting set for mode+bet."""
    try:
        bet = int(bet_amount or 0)
        if bet <= 0:
            return
        r = _get_redis()
        key = waiting_set_key(is_two_player, bet)
        r.sadd(key, str(game_id))
        r.expire(key, TTL_SECONDS)
    except Exception:
        pass


def remove_waiting_room(game_id, is_two_player, bet_amount):
    """Remove game_id from waiting set. No-op if not present."""
    try:
        bet = int(bet_amount or 0)
        if bet <= 0:
            return
        _get_redis().srem(waiting_set_key(is_two_player, bet), str(game_id))
    except Exception:
        pass


def get_waiting_rooms(is_two_player, bet_amount):
    """Return list of game_ids waiting for opponents for this mode+bet."""
    try:
        bet = int(bet_amount or 0)
        if bet <= 0:
            return []
        return list(_get_redis().smembers(waiting_set_key(is_two_player, bet)))
    except Exception:
        return []


# ==========================================================
# ✅ NEW: PLAYER LOBBY INDEX
#
# Tracks which lobby a player is currently waiting in.
# Used to clean up stale lobbies when the same player starts a
# new matchmaking request — O(1) instead of scanning all states.
# ==========================================================

def player_lobby_key(player_token):
    return f"{PLAYER_LOBBY_PREFIX}{player_token}"


def set_player_lobby(player_token, game_id):
    try:
        _get_redis().set(player_lobby_key(player_token), str(game_id), ex=TTL_SECONDS)
    except Exception:
        pass


def get_player_lobby(player_token):
    try:
        val = _get_redis().get(player_lobby_key(player_token))
        return val if val else None
    except Exception:
        return None


def clear_player_lobby(player_token):
    try:
        _get_redis().delete(player_lobby_key(player_token))
    except Exception:
        pass