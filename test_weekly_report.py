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
        blocks = report.report_blocks(result)
        self.assertTrue(any(b['text']['text'].startswith('*④ 이번 주 완료 업무') for b in blocks))

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
        self.assertEqual(len([line for line in intro.splitlines() if line]), 8)

    def test_friday_encouragement_rotates_weekly_and_stays_stable_on_retry(self):
        first = dt.date(2026, 10, 23)
        messages = [report.friday_encouragement(first + dt.timedelta(weeks=i)) for i in range(6)]
        self.assertEqual(len(set(messages)), 6)
        self.assertEqual(report.friday_encouragement(first), messages[0])
        self.assertEqual(report.friday_encouragement(first + dt.timedelta(weeks=6)), messages[0])
        self.assertTrue(messages[0].startswith('이번 주도 각자의 자리에서 애써주셔서 감사합니다.'))
        start = dt.datetime(2026, 10, 19, tzinfo=report.KST)
        self.assertIn(messages[0], report.introduction(start, start, first, True))
        self.assertNotIn(messages[0], report.introduction(start, start, first, False))

    def test_monday_and_friday_mentions_are_in_parent_once(self):
        mentions = '<!subteam^S_TEST> <@U_REVIEWER> <@U_CEO>'
        start = dt.datetime(2026, 10, 12, tzinfo=report.KST)
        cutoff = start.replace(hour=9)
        with patch.object(report, 'GROUP', mentions):
            for friday in (False, True):
                intro = report.introduction(start, cutoff, cutoff.date(), friday)
                self.assertEqual(intro.count(mentions), 1)
                self.assertNotIn(mentions, report.render([self.item], self.monday, friday))

    def test_monday_greetings_rotate_separately_and_remain_stable_on_retry(self):
        first = dt.date(2026, 10, 26)
        messages = [report.monday_encouragement(first + dt.timedelta(weeks=i)) for i in range(6)]
        self.assertEqual(len(set(messages)), 6)
        self.assertEqual(report.monday_encouragement(first), messages[0])
        self.assertEqual(report.monday_encouragement(first + dt.timedelta(weeks=6)), messages[0])
        self.assertTrue(messages[0].startswith('새로운 한 주가 시작됐습니다.'))
        start = dt.datetime(2026, 10, 26, tzinfo=report.KST)
        self.assertIn(messages[0], report.introduction(start, start, first, False))
        self.assertNotIn(messages[0], report.introduction(start, start, first, True))

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

    def test_report_uses_expanded_selectable_text_instead_of_table_viewport(self):
        self.item['worker'] = '<@UWORKER>'
        text = report.render([self.item], self.monday, False)
        blocks = report.report_blocks(text)
        self.assertTrue(all(b['type'] == 'section' and b['expand'] is True for b in blocks))
        content = '\n\n'.join(b['text']['text'] for b in blocks)
        self.assertIn('<@UWORKER>', content)
        self.assertIn('요청자 → 작업자:', content)
        self.assertIn('|스레드>', content)
        self.assertNotIn('| --- |', content)
        self.assertTrue(all(len(b['text']['text']) <= 3000 for b in blocks))

    def legacy_reply(self):
        def rich(text):
            return {'type': 'rich_text', 'elements': [{'type': 'rich_text_section',
                    'elements': [{'type': 'text', 'text': text}]}]}
        roles = rich('확인 필요 → ')
        roles['elements'][0]['elements'].append({'type': 'user', 'user_id': 'UWORKER'})
        status = rich('일정 확인 필요')
        status['elements'][0]['elements'].append({'type': 'link', 'url': report.WORKSPACE + '/archives/C_TEST/p100000001', 'text': '스레드'})
        rows = [[rich(t) for t in ('업무', '요청자 → 작업자', '마감·일정', '상태·확인 사항')],
                [rich('① 이번 주 주요 업무'), rich(' '), rich(' '), rich(' ')],
                [rich('기존 업무'), roles, rich('10/16'), status],
                [rich('④ 이번 주 완료 업무'), rich(' '), rich(' '), rich(' ')],
                [rich('해당 없음'), rich(' '), rich(' '), rich(' ')]]
        return {'ts': '101.000001', 'user': report.BOT, 'text': '기존 표',
                'blocks': [{'type': 'table', 'rows': rows}]}

    def test_reformat_updates_same_reply_preserving_facts_mentions_and_links(self):
        parent = {'ts': '100.000001'}
        original = self.legacy_reply()
        text = report.table_text(original)
        blocks = report.report_blocks(text)
        verified = dict(original, text=text, blocks=blocks)
        with patch.object(report, 'thread', return_value=[parent, verified]), patch.object(report, 'slack') as update:
            report.reformat_existing(parent, [original], False)
        update.assert_called_once()
        self.assertEqual(update.call_args.args[0], 'chat.update')
        payload = update.call_args.args[1]
        self.assertEqual(payload['ts'], original['ts'])
        self.assertEqual(payload['attachments'], [])
        self.assertNotIn('text', payload)  # Retain fallback; chat.update has a 4,000-character cap.
        visible = '\n\n'.join(b['text']['text'] for b in payload['blocks'])
        self.assertIn('기존 업무', visible)
        self.assertIn('<@UWORKER>', visible)
        self.assertIn('10/16', visible)
        self.assertIn('일정 확인 필요', visible)
        self.assertIn('|스레드>', visible)
        self.assertIn('④ 이번 주 완료 업무', visible)
        self.assertTrue(all(b['expand'] is True and b['type'] == 'section' for b in payload['blocks']))

    def test_long_existing_reply_changes_layout_without_resubmitting_long_fallback(self):
        original = self.legacy_reply()
        original['text'] = '원본' * 2000
        visible = report.table_text(original)
        updated = dict(original, blocks=report.report_blocks(visible))
        parent = {'ts': '100.000001'}
        with patch.object(report, 'thread', return_value=[parent, updated]), patch.object(report, 'slack') as update:
            report.reformat_existing(parent, [original], False)
        self.assertNotIn('text', update.call_args.args[1])
        self.assertEqual(updated['text'], original['text'])
        self.assertEqual('\n\n'.join(b['text']['text'] for b in update.call_args.args[1]['blocks']), visible)

    def test_reformat_readback_accepts_slack_generated_block_ids_and_text_defaults(self):
        original = self.legacy_reply()
        blocks = report.report_blocks(report.table_text(original))
        returned = [dict(b, block_id='generated-' + str(i), text=dict(b['text'], verbatim=False))
                    for i, b in enumerate(blocks)]
        parent = {'ts': '100.000001'}
        with patch.object(report, 'thread', return_value=[parent, dict(original, blocks=returned)]), \
             patch.object(report, 'slack') as update:
            report.reformat_existing(parent, [original], False)
        update.assert_called_once()

    def test_reformat_is_dry_by_default_and_does_not_repeat_completed_update(self):
        original = self.legacy_reply()
        with patch.object(report, 'slack') as update:
            report.reformat_existing({'ts': '100.000001'}, [original], True)
        update.assert_not_called()
        original['blocks'] = report.report_blocks(report.table_text(original))
        with patch.object(report, 'slack') as update:
            report.reformat_existing({'ts': '100.000001'}, [original], False)
        update.assert_not_called()

    def test_reformat_refuses_unknown_content_and_other_authors(self):
        original = self.legacy_reply()
        original['user'] = 'UOTHER'
        with patch.object(report, 'slack') as update, self.assertRaises(report.Stop):
            report.reformat_existing({'ts': '100.000001'}, [original], False)
        update.assert_not_called()
        original['user'] = report.BOT
        original['blocks'][0]['rows'][2][0] = {'type': 'image', 'image_url': 'https://example.com/image'}
        with self.assertRaises(report.Stop):
            report.table_text(original)

    def test_reformat_path_does_not_collect_or_regenerate_report(self):
        original = self.legacy_reply()
        parent = {'ts': '100.000001', 'text': '이번 주 디자인 업무 현황 기준일 2026.10.16'}
        cutoff = dt.datetime(2026, 10, 16, 17, tzinfo=report.KST)
        with patch.dict(report.os.environ, SLACK_BOT_TOKEN='test', OPENAI_API_KEY='test',
                        PUBLISH='true', REFORMAT_EXISTING='true'), \
             patch.object(report, 'report_period', return_value=(self.monday, cutoff.date(), True, cutoff)), \
             patch.object(report, 'slack', return_value={'team_id': report.TEAM, 'user_id': report.BOT}), \
             patch.object(report, 'pages', return_value=[parent]), \
             patch.object(report, 'thread', return_value=[parent, original]), \
             patch.object(report, 'collect') as collect, \
             patch.object(report, 'summarize') as summarize, \
             patch.object(report, 'reformat_existing') as reformat:
            report.main()
        reformat.assert_called_once_with(parent, [original], False)
        collect.assert_not_called()
        summarize.assert_not_called()

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

    def test_ambiguous_completion_is_visible_without_invented_date(self):
        self.item.update(section='done', completed_date='2026-10-16',
                         status='10/16 전체 완료', deadline='10/16 완료',
                         facts=[dict(kind='completion', source_id='E1')])
        self.sources['100.000001'][0].update(text='전체 게시 완료했습니다.',
            ts=str(dt.datetime(2026, 10, 16, 14, tzinfo=report.KST).timestamp()))
        result = report.ground_uncertain_completions([self.item], self.sources, self.monday, True)
        report.validate(result, self.sources, self.monday, True)
        self.assertEqual(result[0]['section'], 'coordination')
        self.assertEqual(result[0]['completed_date'], '')
        self.assertEqual(result[0]['deadline'], '확인 필요')
        self.assertIn('확인 필요', result[0]['status'])
        rendered = report.render(result, self.monday, True)
        self.assertNotIn('10/16 전체 완료', rendered)
        self.assertIn('완료 여부·완료일을 원문에서 확인하지 못함', rendered)
        self.assertIn('확인 필요', str(report.report_blocks(rendered)))

    def test_missing_invalid_or_unsupported_completion_becomes_review(self):
        for date, text, facts in (
            ('', '전체 게시 완료', [dict(kind='completion', source_id='E1')]),
            ('2026-02-30', '전체 게시 완료', [dict(kind='completion', source_id='E1')]),
            ('2026-10-16', '10/16 제작 완료, 승인 대기', [dict(kind='completion', source_id='E1')]),
            ('2026-10-16', '10/16 완료 예정', [dict(kind='completion', source_id='E1')]),
            ('2026-10-16', '제작 요청', []),
        ):
            with self.subTest(date=date, text=text):
                self.item.update(section='done', completed_date=date, facts=facts)
                self.sources['100.000001'][0]['text'] = text
                result = report.ground_uncertain_completions([self.item], self.sources, self.monday, True)
                report.validate(result, self.sources, self.monday, True)
                self.assertEqual(result[0]['section'], 'coordination')
                self.assertEqual(result[0]['completed_date'], '')

    def test_verified_completion_is_preserved_and_old_completion_not_reopened(self):
        self.item.update(section='done', completed_date='2026-10-09',
                         facts=[dict(kind='completion', source_id='E1')])
        self.sources['100.000001'][0]['text'] = '10/9 전체 게시 완료'
        self.assertEqual(report.ground_uncertain_completions([self.item], self.sources, self.monday, True), [])
        result = report.ground_uncertain_completions([self.item], self.sources, self.monday, False)
        self.assertEqual(result[0]['section'], 'done')
        self.assertEqual(result[0]['completed_date'], '2026-10-09')

    def test_completion_fallback_cannot_hide_invalid_references_or_duplicates(self):
        self.item.update(section='done', completed_date='', facts=[dict(kind='completion', source_id='E_MISSING')])
        with self.assertRaises(report.Stop):
            report.ground_uncertain_completions([self.item], self.sources, self.monday, True)
        self.item['facts'] = [dict(kind='completion', source_id='E1'), dict(kind='completion', source_id='E_MISSING')]
        with self.assertRaises(report.Stop):
            report.ground_uncertain_completions([self.item], self.sources, self.monday, True)
        self.item['facts'] = [dict(kind='completion', source_id='E1')]
        with self.assertRaises(report.Stop):
            report.ground_uncertain_completions([self.item, dict(self.item)], self.sources, self.monday, True)
        self.item['completed_date'] = '2026-10-09'
        self.sources['100.000001'][0]['text'] = '10/9 전체 게시 완료'
        with self.assertRaises(report.Stop):
            report.ground_uncertain_completions([self.item, dict(self.item, section='main')],
                                                self.sources, self.monday, True)

    def test_main_publishes_report_when_completion_date_is_unknown(self):
        self.item.update(section='done', completed_date='2026-10-16',
                         facts=[dict(kind='completion', source_id='E1')])
        self.sources['100.000001'][0]['text'] = '전체 게시 완료'
        day = dt.date(2026, 10, 16)
        cutoff = dt.datetime(2026, 10, 16, 17, tzinfo=report.KST)
        with patch.dict(report.os.environ, SLACK_BOT_TOKEN='test', OPENAI_API_KEY='test', PUBLISH='true'), \
             patch.object(report, 'report_period', return_value=(self.monday, day, True, cutoff)), \
             patch.object(report, 'slack', return_value={'team_id': report.TEAM, 'user_id': report.BOT}), \
             patch.object(report, 'pages', return_value=[]), \
             patch.object(report, 'collect', return_value=self.sources), \
             patch.object(report, 'summarize', return_value=[self.item]) as summarize, \
             patch.object(report, 'publish') as publish:
            report.main()
        summarize.assert_called_once()
        publish.assert_called_once()
        self.assertIn('완료 여부·완료일을 원문에서 확인하지 못함', publish.call_args.args[2])

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

    def test_update_diagnostic_reports_only_machine_readable_error_code(self):
        with patch.dict(report.os.environ, SLACK_BOT_TOKEN='test'), \
             patch.object(report, 'request_json', return_value={
                 'ok': False, 'error': 'block_mismatch', 'private_detail': 'not for logs'}), \
             self.assertRaises(report.Stop) as stopped:
            report.slack('chat.update', {}, write=True)
        self.assertEqual(str(stopped.exception), 'chat.update: block_mismatch')
        with patch.dict(report.os.environ, SLACK_BOT_TOKEN='test'), \
             patch.object(report, 'request_json', return_value={'ok': False, 'error': 'private response text'}), \
             self.assertRaises(report.Stop) as stopped:
            report.slack('chat.update', {}, write=True)
        self.assertEqual(str(stopped.exception), 'chat.update: request rejected')


if __name__ == '__main__':
    unittest.main()
