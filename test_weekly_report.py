import datetime as dt
import unittest
import io
import urllib.error
from unittest.mock import patch
import weekly_report as report


class WeeklyReportTests(unittest.TestCase):
    def setUp(self):
        config = patch.multiple(report, CHANNEL='C_TEST', BOT='U_TEST', TEAM='T_TEST',
                                WORKSPACE='https://example.slack.com', GROUP='<!subteam^S_TEST>',
                                CHANNEL_NAME='test_design', REPORT_POLICY='Preserve confirmed corrections.')
        config.start()
        self.addCleanup(config.stop)
        self.monday = dt.date(2026, 10, 12)
        self.sources = {'100.000001': [{'ts': '100.000001', 'evidence_id': 'E1', 'user': 'U_REQUESTER',
                        'text': '제작 요청합니다. <@UWORKER> 작업. 완료 10/9'}]}
        self.item = dict(task='이미지', requester='확인 필요', worker='확인 필요', deadline='확인 필요',
                         status='확인 필요', thread_ts='100.000001', completed_date='', section='main', facts=[])

    def test_roles_require_verified_quotes(self):
        self.item['worker'] = '<@UWORKER>'
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)
        self.item['facts'] = [dict(kind='worker', source_id='E1')]
        report.validate([self.item], self.sources, self.monday, False)
        self.item['facts'][0]['source_id'] = 'E_MISSING'
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)

    def test_completion_periods_are_distinct_for_monday_and_friday(self):
        self.item.update(section='done', completed_date='2026-10-09',
                         facts=[dict(kind='completion', source_id='E1')])
        report.validate([self.item], self.sources, self.monday, False)
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, True)
        self.item['completed_date'] = '2026-10-16'
        self.sources['100.000001'][0]['text'] = '전체 게시 완료 10/16'
        report.validate([self.item], self.sources, self.monday, True)
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)
        self.item['completed_date'] = '2026-10-01'
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)

    def test_friday_completion_still_needs_real_completion_evidence(self):
        self.item.update(section='done', completed_date='2026-10-16',
                         facts=[dict(kind='completion', source_id='E_MISSING')])
        report.ground_uncertain_roles([self.item], self.sources)
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, True)
        self.item['facts'] = [dict(kind='completion', source_id='E1')]
        self.sources['100.000001'][0]['text'] = '시안 전달드립니다. 검토 부탁드립니다.'
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, True)

    def test_friday_renders_four_sections_with_current_week_completion(self):
        self.item.update(section='done', completed_date='2026-10-16',
                         facts=[dict(kind='completion', source_id='E1')])
        result = report.render([self.item], self.monday, True)
        self.assertIn('④ 이번 주 완료 업무 ㅣ 10/12~10/16', result)
        self.assertIn('① 이번 주 주요 업무 ㅣ 10/12~10/18', result)
        self.assertNotIn('전주 완료', result)
        self.assertIn('이미지', result)
        blocks = report.table_blocks([self.item], self.monday, True)
        headings = [r[0]['elements'][0]['elements'][0].get('text', '') for r in blocks[0]['rows']]
        self.assertTrue(any(h.startswith('④ 이번 주 완료 업무') for h in headings))

    def test_manual_checks_use_last_complete_report_window(self):
        now = dt.datetime(2026, 10, 20, 10, tzinfo=report.KST)
        monday, day, friday, cutoff = report.report_period(now, 'friday', True)
        self.assertEqual((monday, day, friday), (dt.date(2026, 10, 12), dt.date(2026, 10, 16), True))
        self.assertEqual(cutoff, dt.datetime(2026, 10, 16, 17, tzinfo=report.KST))
        monday, day, friday, cutoff = report.report_period(now, 'monday', True)
        self.assertEqual((monday, day, friday), (dt.date(2026, 10, 19), dt.date(2026, 10, 19), False))
        self.assertEqual(cutoff, dt.datetime(2026, 10, 19, 9, tzinfo=report.KST))

    def test_scheduled_publish_still_enforces_day_and_two_hour_window(self):
        for now, mode in ((dt.datetime(2026, 10, 20, 10, tzinfo=report.KST), 'monday'),
                          (dt.datetime(2026, 10, 23, 16, tzinfo=report.KST), 'friday'),
                          (dt.datetime(2026, 10, 23, 19, 1, tzinfo=report.KST), 'friday')):
            with self.assertRaises(report.Stop):
                report.report_period(now, mode, False)
        now = dt.datetime(2026, 10, 23, 17, 20, tzinfo=report.KST)
        self.assertEqual(report.report_period(now, 'auto', False)[3],
                         dt.datetime(2026, 10, 23, 17, tzinfo=report.KST))

    def test_friday_intro_includes_configured_mentions_and_required_scope(self):
        start = dt.datetime(2026, 10, 12, tzinfo=report.KST)
        cutoff = dt.datetime(2026, 10, 16, 17, tzinfo=report.KST)
        intro = report.introduction(start, cutoff, cutoff.date(), True)
        self.assertIn(report.GROUP, intro)
        self.assertIn('`#test_design`', intro)
        self.assertEqual(len([line for line in intro.splitlines() if line]), 6)

    def test_monday_and_friday_mentions_are_in_parent_once(self):
        mentions = '<!subteam^S_TEST> <@U_REVIEWER> <@U_CEO>'
        start = dt.datetime(2026, 10, 12, tzinfo=report.KST)
        cutoff = start.replace(hour=9)
        with patch.object(report, 'GROUP', mentions):
            for friday in (False, True):
                intro = report.introduction(start, cutoff, cutoff.date(), friday)
                self.assertEqual(intro.count(mentions), 1)
                self.assertNotIn(mentions, report.render([self.item], self.monday, friday))

    def test_length_and_inline_link(self):
        result = report.render([self.item], self.monday, False)
        self.assertIn('|스레드>', result)
        self.assertIn('10/12~10/18', result)
        self.assertIn('10/05~10/11', result)
        self.item['status'] = '긴내용' * 2000
        with self.assertRaises(report.Stop):
            report.render([self.item], self.monday, False)

    def test_stage_delivery_is_not_treated_as_overall_completion(self):
        self.sources['100.000001'][0]['text'] = '시안 전달드립니다. 검토 부탁드립니다.'
        self.item['facts'] = [dict(kind='completion', source_id='E1')]
        report.validate([self.item], self.sources, self.monday, False)
        self.item.update(section='done', completed_date='2026-10-09')
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)

    def test_native_slack_table_places_link_in_last_cell(self):
        self.item['worker'] = '<@UWORKER>'
        blocks = report.table_blocks([self.item], self.monday, False)
        self.assertEqual(blocks[0]['type'], 'table')
        row = blocks[0]['rows'][2]
        self.assertEqual(row[1]['elements'][0]['elements'][-1], {'type': 'user', 'user_id': 'UWORKER'})
        self.assertEqual(row[3]['elements'][0]['elements'][-1]['text'], '스레드')
        self.assertEqual(len(row), 4)

    def test_unsupported_role_becomes_confirmation_required(self):
        self.item['worker'] = '<@UWRONG>'
        self.item['facts'] = [dict(kind='worker', source_id='E1')]
        report.ground_uncertain_roles([self.item], self.sources)
        self.assertEqual(self.item['worker'], '확인 필요')
        self.assertEqual(self.item['facts'], [])
        report.validate([self.item], self.sources, self.monday, False)

    def test_role_schema_and_citation_support_slack_named_mentions(self):
        self.sources['100.000001'][0]['text'] = '<@UWORKER|sample> 작업 요청합니다.'
        self.item['worker'] = '<@UWORKER>'
        self.item['facts'] = [dict(kind='worker', source_id='E1')]
        report.ground_uncertain_roles([self.item], self.sources)
        report.validate([self.item], self.sources, self.monday, False)
        self.assertEqual(self.item['worker'], '<@UWORKER>')
        properties = report.schema(self.sources)['properties']['items']['items']['properties']
        self.assertIn('<@UWORKER>', properties['worker']['enum'])
        self.assertNotIn('<@UWRONG>', properties['worker']['enum'])

    def test_completed_claim_rejects_deadline_negative_and_pending_approval(self):
        self.item.update(section='done', completed_date='2026-10-09',
                         facts=[dict(kind='completion', source_id='E1')])
        for text in ('10/9 마감', '10/9 미완료', '10/9 완료 예정', '10/9 완료되지 않았습니다.',
                     '10/9 제작 완료, 승인 대기', '10/9 완료 여부 확인 필요', '10/9 종료 전 검토',
                     '10/9 마감 완료 예정', '10/9 완료가 안되었습니다.', '10/9 완료됐나요?'):
            with self.subTest(text=text):
                self.sources['100.000001'][0]['text'] = text
                with self.assertRaises(report.Stop):
                    report.validate([self.item], self.sources, self.monday, False)
        for text in ('10/9 전체 게시 완료', '10/9 마감 완료했습니다.', '2026년 10월 9일 종료'):
            with self.subTest(text=text):
                self.sources['100.000001'][0]['text'] = text
                report.validate([self.item], self.sources, self.monday, False)

    def test_completion_date_cannot_be_invented_from_message_timestamp(self):
        self.item.update(section='done', completed_date='2026-10-09',
                         facts=[dict(kind='completion', source_id='E1')])
        self.sources['100.000001'][0].update(text='전체 게시 완료했습니다.',
            ts=str(dt.datetime(2026, 10, 9, 14, tzinfo=report.KST).timestamp()))
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)
        self.sources['100.000001'][0]['text'] = '오늘 전체 게시 완료했습니다.'
        report.validate([self.item], self.sources, self.monday, False)
        self.sources['100.000001'][0]['text'] = '10/8 전체 게시 완료했습니다.'
        with self.assertRaises(report.Stop):
            report.validate([self.item], self.sources, self.monday, False)

    def test_carry_over_sources_older_than_four_reports_are_reopened(self):
        task = {'ts': '100.000001', 'text': '기존 미완료 요청'}
        history = [task] + [{'ts': str(n) + '.000001', 'text': '이번 주 디자인 업무 현황'}
                            for n in range(200, 206)]
        task['ts'] = '1000000000.000001'
        link = report.WORKSPACE + '/archives/' + report.CHANNEL + '/p1000000000000001'
        def report_replies(ts, cutoff):
            if ts == '200.000001':
                return [{'ts': ts, 'text': '보고'}, {'ts': '200.000002', 'user': report.BOT, 'text': link}]
            return [{'ts': ts, 'text': '보고'}]
        with patch.object(report, 'thread', side_effect=report_replies) as fetch:
            result = report.collect(history, 2000000000, '3000000000')
        self.assertIn(task['ts'], result)
        self.assertEqual(fetch.call_count, 6)

    def test_carry_over_source_filtered_as_bot_fails_closed(self):
        root = {'ts': '1000000000.000001', 'text': '기존 요청', 'user': report.BOT}
        history = [root, {'ts': '2000000000.000001', 'text': '이번 주 디자인 업무 현황'}]
        link = report.WORKSPACE + '/archives/' + report.CHANNEL + '/p1000000000000001'
        with patch.object(report, 'thread', return_value=[{'text': '보고'}, {'text': link, 'user': report.BOT}]):
            with self.assertRaises(report.Stop):
                report.collect(history, 2100000000, '3000000000')

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

    def test_openai_quota_error_is_distinguished_without_body_logging(self):
        error = urllib.error.HTTPError('https://api.openai.com/v1/responses', 429, 'quota', {},
            io.BytesIO(b'{"error":{"code":"insufficient_quota","message":"private account info"}}'))
        with patch('urllib.request.urlopen', side_effect=error), self.assertRaises(report.Stop) as stopped:
            report.request_json('https://api.openai.com/v1/responses', 'test', {})
        self.assertEqual(str(stopped.exception), 'OpenAI HTTP 429: insufficient_quota')

    def test_slack_write_is_not_retried_after_429(self):
        error = urllib.error.HTTPError('https://slack.com/api/chat.postMessage', 429, 'rate', {'Retry-After': '1'}, None)
        with patch('urllib.request.urlopen', side_effect=error) as call, self.assertRaises(report.Stop):
            report.request_json('https://slack.com/api/chat.postMessage', 'test', {})
        self.assertEqual(call.call_count, 1)


if __name__ == '__main__':
    unittest.main()
