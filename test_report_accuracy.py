"""Synthetic regressions for source chronology, completion and table delivery."""
import datetime as dt
import json
import unittest
from unittest.mock import patch
import weekly_report as r


class AccuracyTests(unittest.TestCase):
    def test_early_runner_waits_without_advancing_cutoff_or_repeating_a_late_wait(self):
        now = dt.datetime(2026,10,26,8,42,tzinfo=r.KST)
        with patch.object(r.time,'sleep') as pause:
            r.wait_for_nominal(now,'30 23 * * 0')
            pause.assert_called_once_with(18*60)
        with patch.object(r.time,'sleep') as pause:
            r.wait_for_nominal(now.replace(hour=9),'30 23 * * 0')
            r.wait_for_nominal(now,'')
            pause.assert_not_called()
        with self.assertRaises(r.Stop):
            r.wait_for_nominal(now,'30 7 * * 5')

    def setUp(self):
        p = patch.multiple(r, CHANNEL='CTEST', BOT='UBOT', WORKSPACE='https://example.slack.com')
        p.start()
        self.addCleanup(p.stop)
        self.monday = dt.date(2026, 10, 19)
        self.stamp = str(dt.datetime(2026, 10, 22, 15, tzinfo=r.KST).timestamp())
        self.sources = {'1.000001': [{'ts': self.stamp, 'evidence_id': 'E1', 'user': 'UALPHA',
                                    'text': '최종 수정 완료하여 HTML 전달드립니다. 상품 셋팅 확인 부탁드립니다.'}]}
        self.item = dict(task='PDP 디자인 최종본', requester='확인 필요', worker='<@UALPHA>',
                         deadline='10/23', status='최종 디자인/HTML 전달 완료; 상품 셋팅 별도',
                         thread_ts='1.000001', completed_date='', section='done',
                         facts=[dict(kind='worker', source_id='E1'), dict(kind='completion', source_id='E1')])

    def test_confirmed_design_without_exact_date_remains_done(self):
        items = r.ground_uncertain_completions([self.item], self.sources, self.monday, True)
        r.validate(items, self.sources, self.monday, True)
        self.assertEqual(items[0]['section'], 'done')
        self.assertEqual(items[0]['completed_date'], '')
        self.assertEqual(items[0]['deadline'], '10/23')
        self.assertIn('상품 셋팅 별도', items[0]['status'])

    def test_invalid_date_does_not_erase_completion_or_deadline(self):
        self.item['completed_date'] = '2026-02-30'
        items = r.ground_uncertain_completions([self.item], self.sources, self.monday, True)
        self.assertEqual(items[0]['section'], 'done')
        self.assertEqual(items[0]['deadline'], '10/23')
        self.assertIn('실제 완료일 확인 필요', items[0]['status'])

    def test_old_completion_confirmation_is_not_reopened(self):
        self.sources['1.000001'][0]['ts'] = str(dt.datetime(2026, 10, 16, tzinfo=r.KST).timestamp())
        self.assertEqual(r.ground_uncertain_completions([self.item], self.sources, self.monday, True), [])

    def test_future_delivery_and_first_draft_are_not_final_completion(self):
        for text in ('최종 HTML 전달 예정입니다.', '최종 수정 완료하겠습니다.', '1차 시안 전달드립니다. 검토 부탁드립니다.'):
            self.assertFalse(r.weekly_completion(text), text)

    def test_broadcast_reply_is_collected_once_under_original_root(self):
        root = dict(ts='10.000001', text='디자인 요청', reply_count=2, latest_reply='30.000001')
        reply = dict(ts='30.000001', thread_ts=root['ts'], subtype='thread_broadcast', text='최종 전달 완료')
        with patch.object(r, 'thread', return_value=[root, reply]) as read:
            sources = r.collect([root, reply], 20, '40')
        self.assertEqual(list(sources), [root['ts']])
        self.assertEqual(len(sources[root['ts']]), 2)
        read.assert_called_once_with(root['ts'], '40')

    def test_bot_receipt_is_not_source_evidence(self):
        root = dict(ts='10.000001', text='디자인 요청', reply_count=1, latest_reply='30.000001')
        with patch.object(r, 'thread', return_value=[root, dict(ts='30.000001', bot_id='BRECEIPT', text='참조확인완료')]):
            sources = r.collect([root], 20, '40')
        self.assertEqual(len(sources[root['ts']]), 1)

    def test_multiple_workers_must_each_have_cited_assignment(self):
        self.item['worker'] = '<@UALPHA> + <@UBETA>'
        self.sources['1.000001'].append(dict(ts=self.stamp, evidence_id='E2', user='ULEAD', text='<@UBETA> 함께 작업 담당'))
        self.item['facts'].append(dict(kind='worker', source_id='E2'))
        r.validate([self.item], self.sources, self.monday, True)
        self.item['worker'] += ' + <@UUNKNOWN>'
        with self.assertRaises(r.Stop):
            r.validate([self.item], self.sources, self.monday, True)

    def test_verified_unique_name_assignment_is_recognized(self):
        cfg = json.dumps({'designers': [dict(id='UBETA', name='김가람')]})
        with patch.dict(r.os.environ, BOARD_CONFIG=cfg):
            self.assertIn('UBETA', r.role_actors(dict(user='ULEAD', text='가람님 담당으로 진행')))

    def test_tables_retain_every_row_link_and_mention_in_short_parts(self):
        items = [dict(self.item, task='작업 ' + str(n)) for n in range(8)]
        text = r.render(items, self.monday, True)
        parts = r.report_parts(text)
        tables = [b for p in parts for b in p['blocks'] if b['type'] == 'table']
        self.assertTrue(all(len(b['rows']) <= 4 for b in tables))
        visible = '\n'.join(r.table_text({'blocks': [b]}) for b in tables)
        for n in range(8):
            self.assertEqual(visible.count('작업 ' + str(n)), 1)
        self.assertEqual(visible.count('<@UALPHA>'), 8)
        self.assertEqual(visible.count('|스레드>'), 8)
        self.assertEqual(sum('③ 이번 주 완료 업무' in p['text'] for p in parts), 1)
        titles = [title for p in parts for title in r.section_titles(p)]
        self.assertEqual(len(titles), 4)
        self.assertEqual(len(set(titles)), 4)
        self.assertEqual(sum('③ 이번 주 완료 업무' in title for title in titles), 1)
        self.assertTrue(r.complete_parts([dict(ts=str(n), **p) for n, p in enumerate(parts)]))

    def test_monday_excludes_completion_and_friday_has_four_status_sections(self):
        for friday in (True, False):
            headings = r.headings(self.monday, friday)
            expected = ['main', 'planned', 'done', 'coordination'] if friday else ['main', 'planned', 'coordination']
            self.assertEqual([key for key, _ in headings], expected)
            self.assertTrue(headings[0][1].startswith('① 진행 중 업무'))
            self.assertEqual(headings[1][1], '② 진행 예정 업무')
            self.assertEqual(headings[-1][1], ('④' if friday else '③') + ' 보류·확인 필요 업무')
        self.assertEqual(r.headings(self.monday, True)[2][1], '③ 이번 주 완료 업무 ㅣ 10/19~10/23')

    def test_monday_omits_proven_completion_rows_and_even_empty_completion_headings(self):
        self.sources['1.000001'][0]['ts'] = str(dt.datetime(2026, 10, 16, tzinfo=r.KST).timestamp())
        items = r.ground_uncertain_completions([self.item], self.sources, self.monday, False)
        self.assertEqual(items, [])
        # Defense in depth: direct rendering cannot leak a done row on Monday.
        detail = r.render([self.item, dict(self.item, section='main', task='진행 중 테스트')], self.monday, False)
        self.assertNotIn('완료 업무', detail)
        self.assertNotIn('PDP 디자인 최종본', detail)
        self.assertIn('진행 중 테스트', detail)
        self.assertEqual(len(r.headings(self.monday, False)), 3)

    def test_regrouping_preserves_existing_reply_slots_with_real_rows(self):
        items = [dict(self.item, section='done', task='작업 ' + str(n)) for n in range(7)]
        detail = r.render(items, self.monday, True)
        natural = r.report_parts(detail)
        padded = r.report_parts(detail, minimum_parts=len(natural) + 1)
        self.assertEqual(len(padded), len(natural) + 1)
        content = '\n'.join(r.table_text({'blocks': [b]}) for p in padded for b in p['blocks'] if b['type'] == 'table')
        for n in range(7):
            self.assertEqual(content.count('작업 ' + str(n)), 1)
        titles = [title for p in padded for title in r.section_titles(p)]
        self.assertEqual(len(titles), 4)
        self.assertTrue(r.complete_parts([dict(ts=str(n), **p) for n, p in enumerate(padded)]))

    def test_correction_updates_original_reply_preserves_human_comments_and_verifies_rows(self):
        parent = dict(ts='1.000001')
        old = dict(ts='2.000001', user=r.BOT, text='기존 보고')
        human = dict(ts='3.000001', user='UHUMAN', text='사람 댓글')
        detail = r.render([self.item], self.monday, True)
        parts = r.report_parts(detail)
        actual = [dict(ts=str(n+2)+'.000001', user=r.BOT, **part) for n, part in enumerate(parts)]
        with patch.object(r, 'thread', side_effect=[[parent, old, human], [parent, human] + actual]), patch.object(r, 'slack') as write:
            r.replace_details(parent, detail)
        self.assertEqual(write.call_args_list[0].args[0], 'chat.update')
        self.assertEqual(write.call_args_list[0].args[1]['ts'], old['ts'])
        self.assertTrue(all(c.args[1].get('ts') != human['ts'] for c in write.call_args_list))

    def test_reviewed_correction_cannot_create_parent_or_change_scheduled_window(self):
        now = dt.datetime(2026, 10, 24, 12, tzinfo=r.KST)
        self.assertEqual(r.correction_period(now, 'friday', '2026-10-23')[1], dt.date(2026, 10, 23))
        with self.assertRaises(r.Stop):
            r.report_period(now, 'friday', False)
        with self.assertRaises(r.Stop):
            r.correction_period(now, 'monday', '2026-10-23')
        with self.assertRaises(r.Stop):
            r.correction_period(now, 'friday', '2026-10-02')


if __name__ == '__main__':
    unittest.main()
