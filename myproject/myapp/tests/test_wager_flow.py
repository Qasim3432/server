# myapp/tests/test_wager_flow.py

from django.test import TransactionTestCase
from myapp.models import GameRoom, GameHistory, UserProfileBalance, SystemConfiguration
from myapp.services.wager_service import join_wager, finalize_wager_game, cancel_wager

class WagerJoinTests(TransactionTestCase):
    def setUp(self):
        self.p1 = UserProfileBalance.objects.create(device_token="p1", coins=1000)
        self.p2 = UserProfileBalance.objects.create(device_token="p2", coins=1000)
        SystemConfiguration.get_solo()

    def test_first_join_locks_coins(self):
        r = join_wager("p1", "game-1", 100)
        self.assertEqual(r["status"], "success")
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.coins, 900)
        self.assertEqual(self.p1.locked_coins, 100)

    def test_rejoin_lobby_does_not_double_charge(self):
        join_wager("p1", "game-3", 100)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.locked_coins, 100)

        # Issue #3 check
        r = join_wager("p1", "game-3", 100)
        self.assertEqual(r["status"], "success")
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.locked_coins, 100)
        self.assertEqual(self.p1.coins, 900)

class WagerFinalizeTests(TransactionTestCase):
    def setUp(self):
        self.p1 = UserProfileBalance.objects.create(device_token="p1", coins=1000)
        self.p2 = UserProfileBalance.objects.create(device_token="p2", coins=1000)
        SystemConfiguration.get_solo()

    def test_winner_gets_payout(self):
        join_wager("p1", "g1", 100); join_wager("p2", "g1", 100)
        r = finalize_wager_game("g1", "p1")
        self.assertEqual(r["status"], "success")
        self.p1.refresh_from_db(); self.p2.refresh_from_db()
        self.assertGreater(self.p1.coins, 1000)
        self.assertEqual(self.p2.coins, 900)