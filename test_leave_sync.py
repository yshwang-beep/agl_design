import datetime as dt
import os
import unittest
from unittest.mock import patch
import leave_sync


class FakeSlack:
    def __init__(self, messages, channels=None):
        self.messages = messages
        self.channels = channels or [{'id': 'CSOURCE123', 'name': '03_leave', 'is_private': False}]
        self.calls = []

    def call(self, method):
        return {'team_id': 'TTEST123'}

    def pages(self, method, params, key='messages', max_pages=100):
        self.calls.append((method, params))
        return self.channels if method == 'conversations.list' else self.messages


class LeaveSyncTests(unittest.TestCase):
    def test_explicit_team_notices_only_and_no_replies(self):
        notices = [
            {'ts': '1700000001.000001', 'text': ':palm_tree: [Member] - 11월 11일 하루종일 휴가입니다.', 'user': 'UBOT', 'bot_id': 'BBOT'},
            {'ts': '1700000002.000001', 'text': ':exclamation: [Member] - 11월 11일 하루종일 휴가가 취소되었습니다.', 'bot_id': 'BBOT'},
            {'ts': '1700000003.000001', 'text': ':palm_tree: [Other] - 11월 11일 하루종일 휴가입니다.', 'bot_id': 'BBOT'},
            {'ts': '1700000004.000001', 'text': 'Member will be away for a private reason'},
            {'ts': '1700000005.000001', 'thread_ts': '1700000001.000001', 'text': ':palm_tree: [Member] - 11월 11일 하루종일 휴가입니다.', 'bot_id': 'BBOT'},
        ]
        slack = FakeSlack(notices)
        result = leave_sync.collect(slack, {'team_id': 'TTEST123', 'designers': [{'name': 'Member'}]}, dt.datetime(2026, 11, 11, 11, tzinfo=dt.timezone(dt.timedelta(hours=9))))
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(result['rows'][0]['revision'], notices[0]['ts'])
        self.assertEqual(slack.calls[0][1]['types'], 'public_channel')
        self.assertEqual(result['channelId'], 'CSOURCE123')

    def test_private_or_missing_channel_stops(self):
        with self.assertRaises(leave_sync.board.Stop):
            leave_sync.collect(FakeSlack([], [{'id': 'GPRIVATE', 'name': '03_leave', 'is_private': True}]), {'team_id': 'TTEST123', 'designers': []}, dt.datetime.now(dt.timezone.utc))

    def test_manual_execution_cannot_write(self):
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'BOARD_ENABLED': 'true'}):
            with self.assertRaises(leave_sync.board.Stop):
                leave_sync.execute()


if __name__ == '__main__':
    unittest.main()
