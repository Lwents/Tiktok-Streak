import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streak_history import analyze_history, analyze_reply


class HistoryEvidenceChecks(unittest.TestCase):
    def setUp(self):
        self.today = datetime(2026, 11, 13, 22, tzinfo=timezone(timedelta(hours=7)))
        self.messages = []

    def add(self, days_ago, direction='self', kind=7, scene='', valid=True, hour=12, sender=None):
        at = (self.today - timedelta(days=days_ago)).replace(hour=hour, minute=0)
        self.messages.append({'id': str(len(self.messages)+1), 'at': at.timestamp(), 'day': at.date().isoformat(),
                              'direction': direction, 'type': kind, 'scene': scene, 'valid': valid})
        if sender is not None:
            self.messages[-1]['sender_id'] = str(sender)

    def both(self, days_ago):
        self.add(days_ago, 'self')
        self.add(days_ago, 'peer')

    def snapshot(self):
        return {'today': self.today.date().isoformat(), 'checked_at': self.today.timestamp(),
                'timezone': 'Asia/Bangkok', 'messages': self.messages}

    def test_tiktok_notice_and_three_unbroken_days_confirm_history(self):
        for d in range(3):
            self.both(d)
        self.add(2, 'system', 1, 'streak_interaction_unlock')
        result = analyze_history(self.snapshot())
        self.assertEqual(result['status'], 'history_confirmed')
        self.assertEqual(result['days_lower_bound'], 3)
        self.assertTrue(result['self_sent_today'])

    def test_daily_exchange_alone_is_not_tiktok_confirmation(self):
        for d in range(4):
            self.both(d)
        self.assertEqual(analyze_history(self.snapshot())['status'], 'unknown')

    def test_one_way_messages_do_not_make_a_streak(self):
        for d in range(5):
            self.add(d, 'self')
        self.add(2, 'system', 1, 'streak_interaction_unlock')
        self.assertEqual(analyze_history(self.snapshot())['status'], 'unknown')

    def test_gap_after_old_notice_is_not_confirmed(self):
        for d in (0, 1, 2, 4, 5, 6):
            self.both(d)
        self.add(5, 'system', 1, 'streak_milestone_upgrade')
        result = analyze_history(self.snapshot())
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['days_lower_bound'], 3)

    def test_end_notice_after_milestone_blocks_send(self):
        for d in range(4):
            self.both(d)
        self.add(3, 'system', 1, 'streak_milestone_upgrade')
        self.add(0, 'system', 1, 'streak_end_with_restore')
        self.assertEqual(analyze_history(self.snapshot())['reason'], 'later_end_notice')

    def test_restore_after_end_still_requires_continuous_exchange(self):
        for d in range(4):
            self.both(d)
        self.add(3, 'system', 1, 'streak_end_with_restore')
        self.add(2, 'system', 1, 'streak_new_recover_with_pet')
        self.assertEqual(analyze_history(self.snapshot())['status'], 'history_confirmed')

    def test_restore_day_need_not_have_mutual_messages(self):
        for d in range(6):
            self.both(d)
        self.add(6, 'system', 1, 'streak_end_with_restore_with_pet', hour=10)
        self.add(6, 'system', 1, 'streak_new_recover_with_pet', hour=11)
        self.add(6, 'self')
        result = analyze_history(self.snapshot())
        self.assertEqual(result['status'], 'history_confirmed')
        self.assertEqual(result['days_lower_bound'], 6)
        self.assertTrue(result['restored'])

    def test_restore_today_confirms_without_three_new_mutual_days(self):
        self.add(0, 'system', 1, 'streak_end_with_restore_with_pet', hour=10)
        self.add(0, 'system', 1, 'streak_new_recover_with_pet', hour=11)
        self.add(0, 'self')
        result = analyze_history(self.snapshot())
        self.assertEqual(result['status'], 'history_confirmed')
        self.assertEqual(result['observed_exchange_days'], 0)
        self.assertEqual(result['days_lower_bound'], 3)

    def test_missing_day_after_restore_still_blocks_confirmation(self):
        for d in (0, 1, 3):
            self.both(d)
        self.add(4, 'system', 1, 'streak_new_recover_with_pet')
        self.assertEqual(analyze_history(self.snapshot())['status'], 'unknown')

    def test_restore_variants_are_exact_not_prefix_matches(self):
        for scene in ('streak_new_recover_no_pet', 'streak_new_recover_with_pet_few_restore_left'):
            with self.subTest(scene=scene):
                self.messages = []
                self.add(0, 'system', 1, scene)
                self.assertEqual(analyze_history(self.snapshot())['status'], 'history_confirmed')
        self.messages = []
        self.add(0, 'system', 1, 'streak_new_recover_invitation')
        self.assertEqual(analyze_history(self.snapshot())['status'], 'unknown')

    def test_end_after_same_day_restore_blocks_confirmation(self):
        self.add(0, 'system', 1, 'streak_new_recover_with_pet', hour=10)
        self.add(0, 'system', 1, 'streak_end_with_restore_with_pet', hour=11)
        self.assertEqual(analyze_history(self.snapshot())['reason'], 'later_end_notice')

    def test_invitation_and_user_text_cannot_impersonate_system_notice(self):
        for d in range(4):
            self.both(d)
        self.add(2, 'system', 1, 'streak_pet_invite')
        self.add(2, 'peer', 7, 'streak_interaction_unlock')
        self.assertEqual(analyze_history(self.snapshot())['status'], 'unknown')

    def test_yesterdays_chain_can_need_reply_today(self):
        for d in (1, 2, 3):
            self.both(d)
        self.add(3, 'system', 1, 'streak_interaction_unlock')
        self.add(0, 'peer')
        result = analyze_history(self.snapshot())
        self.assertEqual(result['status'], 'history_confirmed')
        self.assertFalse(result['self_sent_today'])

    def test_duplicate_or_invalid_messages_do_not_fill_missing_direction(self):
        for d in range(3):
            self.add(d, 'self')
            self.add(d, 'peer', valid=False)
        self.add(2, 'system', 1, 'streak_interaction_unlock')
        self.messages += list(self.messages)
        self.assertEqual(analyze_history(self.snapshot())['status'], 'unknown')

    def test_group_streak_can_be_kept_by_two_other_members(self):
        for d in range(4):
            self.add(d, 'peer', sender=20)
            self.add(d, 'peer', sender=30)
        self.add(3, 'system', 1, 'streak_group_unlock')
        result = analyze_history({**self.snapshot(), 'is_group': True})
        self.assertEqual(result['status'], 'history_confirmed')
        self.assertFalse(result['self_sent_today'])
        self.assertEqual(result['days_lower_bound'], 4)

    def test_one_group_sender_is_not_a_daily_exchange(self):
        for d in range(4):
            self.add(d, 'peer', sender=20)
            self.add(d, 'peer', sender=20)
        self.add(3, 'system', 1, 'streak_group_upgrade')
        self.assertEqual(analyze_history({**self.snapshot(), 'is_group': True})['status'], 'unknown')

    def test_group_end_after_restore_blocks_confirmation(self):
        self.add(0, 'system', 1, 'streak_group_recover', hour=10)
        self.add(0, 'system', 1, 'streak_group_end_with_restore', hour=11)
        self.assertEqual(analyze_history({**self.snapshot(), 'is_group': True})['reason'], 'later_end_notice')

    def test_group_restore_repairs_its_day_but_not_later_gaps(self):
        for d in (0, 1):
            self.add(d, 'self', sender=10)
            self.add(d, 'peer', sender=20)
        self.add(2, 'system', 1, 'streak_group_recover')
        self.assertEqual(analyze_history({**self.snapshot(), 'is_group': True})['status'], 'history_confirmed')
        self.messages[-1]['day'] = (self.today-timedelta(days=3)).date().isoformat()
        self.assertEqual(analyze_history({**self.snapshot(), 'is_group': True})['status'], 'unknown')

    def test_group_notice_is_not_accepted_in_single_chat(self):
        for d in range(4):
            self.both(d)
        self.add(2, 'system', 1, 'streak_group_upgrade')
        self.assertEqual(analyze_history(self.snapshot())['status'], 'unknown')

    def test_manual_video_today_satisfies_reply_without_matching_template(self):
        self.add(0, 'self', kind=8)
        self.assertEqual(analyze_reply({**self.snapshot(), 'has_more': True})['status'], 'replied')

    def test_peer_message_does_not_mean_i_replied(self):
        self.add(0, 'peer')
        self.add(1, 'self')
        self.assertEqual(analyze_reply({**self.snapshot(), 'has_more': True})['status'], 'needed')

    def test_incomplete_today_history_is_unknown(self):
        self.add(0, 'peer')
        self.assertEqual(analyze_reply({**self.snapshot(), 'has_more': True})['status'], 'unknown')
        self.assertEqual(analyze_reply({**self.snapshot(), 'has_more': False})['status'], 'needed')

    def test_failed_recalled_or_system_messages_do_not_satisfy_reply(self):
        self.add(0, 'self', valid=False)
        self.add(0, 'self', kind=1, scene='streak_group_upgrade')
        self.add(0, 'peer')
        self.add(1, 'self')
        self.assertEqual(analyze_reply({**self.snapshot(), 'has_more': False})['status'], 'needed')

    def test_reply_skip_expires_at_next_local_day(self):
        self.add(0, 'self')
        midnight=(self.today+timedelta(days=1)).replace(hour=0,minute=0).timestamp()
        result=analyze_reply({**self.snapshot(), 'day_ends_at': midnight})
        self.assertEqual(result['valid_until'], midnight)
        self.today+=timedelta(days=1)
        self.assertEqual(analyze_reply({**self.snapshot(), 'has_more': True})['status'], 'needed')


if __name__ == '__main__':
    unittest.main()
