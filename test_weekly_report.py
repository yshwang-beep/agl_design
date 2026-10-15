import datetime as dt
import unittest
from unittest.mock import patch
import weekly_report as report


class WeeklyReportTests(unittest.TestCase):
    def setUp(self):
        config = patch.multiple(report, CHANNEL='C_TEST', BOT='U_TEST', TEAM='T_TEST',
                                WORKSPACE='https://example.slack.com', GROUP='<!subteam^S_TEST>')
        config.start()
        self.addCleanup(config.stop)
        self.monday = dt.date(2026, 10, 12)
        self.sources = {'100.000001': [{'ts': '100.000001', 'text': '제작 요청합니다. 지은 요청, 송아 작업. 완료 10/9'}]}
        self.item = dict(task='이미지', requester='확인 필요', worker='확인 필요', deadline='확인 필요',
                         status='확인 필요', thread_ts='100.000001', completed_date='', section='main', facts=[])

    def test_roles_require_verified_quotes(self):
        self.item['worker'] = '송아'
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)
        self.item['facts'] = [dict(kind='worker', ts='100.000001', quote='송아 작업')]
        report.validate([self.item], self.sources, self.monday, False)
        self.item['facts'][0]['quote'] = '만들어진 인용'
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)

    def test_completed_friday_rejected_and_previous_week_checked(self):
        self.item.update(section='done', completed_date='2026-10-09',
                         facts=[dict(kind='completion', ts='100.000001', quote='완료 10/9')])
        report.validate([self.item], self.sources, self.monday, False)
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, True)
        self.item['completed_date'] = '2026-10-01'
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)

    def test_length_and_inline_link(self):
        result = report.render([self.item], self.monday, False)
        self.assertIn('|스레드>', result)
        self.assertIn('10/12~10/18', result)
        self.assertIn('10/05~10/11', result)
        self.item['status'] = '긴내용' * 2000
        with self.assertRaises(report.Stop):
            report.render([self.item], self.monday, False)

    def test_old_thread_recent_reply_is_collected(self):
        history = [{'ts': '100.000001', 'text': '오래된 요청', 'reply_count': 1, 'latest_reply': '900.000001'}]
        with patch.object(report, 'thread', return_value=[{'ts': '100.000001', 'text': '원문'}, {'ts': '900.000001', 'text': '신규 댓글'}]) as fetch:
            result = report.collect(history, 800, '1000')
        self.assertIn('100.000001', result)
        fetch.assert_called_once()

    def test_parent_only_gets_reply_no_new_parent(self):
        parent = {'ts': '100.000001', 'text': '인트로'}
        reply = {'ts': '101.000001', 'text': '상세', 'user': report.BOT}
        with patch.object(report, 'thread', side_effect=[[parent], [parent, reply]]), patch.object(report, 'slack') as send:
            report.publish(parent, '인트로', '상세', self.monday)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs, {'write': True})
        self.assertEqual(send.call_args.args[1]['thread_ts'], parent['ts'])

    def test_uncertain_write_is_not_retried(self):
        parent = {'ts': '100.000001', 'text': '인트로'}
        with patch.object(report, 'thread', return_value=[parent]), patch.object(report, 'slack', side_effect=report.Stop('uncertain')) as send:
            with self.assertRaises(report.Stop):
                report.publish(parent, '인트로', '상세', self.monday)
        self.assertEqual(send.call_count, 1)

    def test_verified_absence_allows_one_reply_retry(self):
        parent = {'ts': '100.000001', 'text': '인트로'}
        reply = {'ts': '101.000001', 'text': '상세', 'user': report.BOT}
        with patch.object(report, 'thread', side_effect=[[parent], [parent], [parent, reply]]), patch.object(report, 'slack') as send:
            report.publish(parent, '인트로', '상세', self.monday)
        self.assertEqual(send.call_count, 2)


if __name__ == '__main__':
    unittest.main()
