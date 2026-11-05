import datetime as dt
import unittest
from unittest.mock import patch
import daily_board as daily


class DailyTests(unittest.TestCase):
    def test_window_is_seven_am_kst_and_continues_after_last_success(self):
        date = dt.date(2026, 11, 5)
        start, end = daily.window(date)
        self.assertEqual(end.isoformat(), '2026-11-05T07:00:00+09:00')
        self.assertEqual(start.isoformat(), '2026-10-29T07:00:00+09:00')
        start, _ = daily.window(date, {'meta': {'daily': {'sourceCutoff': '2026-11-03T06:59:59+09:00'}}})
        self.assertEqual(start.isoformat(), '2026-11-03T07:00:00+09:00')
        start, _ = daily.window(date, {'meta': {'daily': {'sourceCutoff': '2026-11-03T06:59:59+09:00'}}}, backfill=True)
        self.assertEqual(start.isoformat(), '2026-10-29T07:00:00+09:00')

    def test_every_day_window_and_no_late_or_future_write(self):
        for n in range(7):
            date = dt.date(2026, 11, 2) + dt.timedelta(days=n)
            daily.ensure_window(dt.datetime.combine(date, dt.time(7), daily.board.KST), date)
            for time in [dt.time(6, 59), dt.time(8, 30)]:
                with self.assertRaises(daily.board.Stop):
                    daily.ensure_window(dt.datetime.combine(date, time, daily.board.KST), date)

    def test_dryrun_never_obtains_write_token(self):
        api = daily.DailyAPI('https://example.workers.dev', '2026-11-05')
        with patch.object(api, 'token') as token:
            for op in ['commit', 'notice-intent', 'notice-result']:
                with self.assertRaises(daily.board.Stop):
                    api.call(op)
            token.assert_not_called()

    def test_backfill_maps_only_historical_commit(self):
        api = daily.DailyAPI('https://example.workers.dev', '2026-11-05', True, True)
        with patch.object(api, 'token', return_value='not-a-real-token'), patch.object(daily.board, 'http_json', return_value={'ok': True}) as request:
            api.call('commit', {'runId': '123'})
            self.assertTrue(request.call_args.args[0].endswith('/daily-backfill'))
            self.assertEqual(request.call_args.args[2]['date'], '2026-11-05')


if __name__ == '__main__':
    unittest.main()
