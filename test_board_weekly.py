import contextlib
import datetime as dt
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

import board_weekly as board


def stamp(day, hour=12):
    return format(dt.datetime(2026, 10, day, hour, tzinfo=board.KST).timestamp(), '.6f')


class BoardTests(unittest.TestCase):
    def test_workboard_uses_the_approved_automation_identity_header(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"ok":true}'
        with patch.object(board.urllib.request, 'build_opener', return_value=opener):
            board.http_json('https://example.workers.dev/api/status', 'synthetic', service='Workboard')
            self.assertEqual(opener.open.call_args.args[0].get_header('User-agent'),
                             'AGL-Design-Workboard-Automation/1.0')
            board.http_json('https://slack.com/api/auth.test', 'synthetic', service='Slack')
            self.assertIsNone(opener.open.call_args.args[0].get_header('User-agent'))

    def test_workboard_diagnostics_expose_only_safe_fixed_codes(self):
        for raw, expected in [(b'error code: 1010\n', 'cloudflare_edge_1010'),
                              (b'{"error":"automation_identity_denied"}', 'automation_identity_denied'),
                              (b'{"error":"PRIVATE_SOURCE_CANARY"}', 'unclassified_rejection'),
                              (b'PRIVATE_SOURCE_CANARY', 'unclassified_rejection')]:
            error = urllib.error.HTTPError('https://example.invalid', 403, 'Denied', {}, io.BytesIO(raw))
            self.assertEqual(board.workboard_error_code(error), expected)

    def setUp(self):
        self.cfg = {'team_id': 'TTEST', 'bot_user_id': 'UBOT', 'workspace_url': 'https://example.slack.com',
            'core_channel_ids': ['CTEST'], 'notice_channel_id': 'CTEST', 'group_id': 'SGROUP',
            'designers': [{'id': 'UTEST' + str(i), 'name': '테스트 담당자 ' + str(i), 'aliases': []} for i in range(8)],
            'collaborators': [{'id': 'UCOLLAB', 'name': '테스트 협업자'}], 'project_keywords': [],
            'excluded_user_ids': [], 'excluded_channel_patterns': []}
        self.now = dt.datetime(2026, 10, 19, 8, tzinfo=board.KST)
        self.period, self.start, self.end, self.monday = board.report_period(self.now)
        self.key = 'CTEST:' + stamp(13)
        self.sources = {self.key: {'channel_id': 'CTEST', 'thread_ts': stamp(13),
            'messages': [{'evidence_id': 'E1', 'ts': stamp(13), 'user': 'UTEST0',
                          'text': '<@UTEST1> 배너 제작 부탁드립니다. 10/16 마감입니다.'},
                         {'evidence_id': 'E2', 'ts': stamp(16), 'user': 'UTEST1',
                          'text': '제가 배너 제작을 진행했습니다. 진행률 80%입니다.'}], 'current_ids': ['E1', 'E2']}}
        self.item = {'title': '합성 배너 업무', 'sourceTaskId': '', 'sourceKey': self.key,
            'owners': ['UTEST1'], 'requester': 'UTEST0', 'collaborators': [], 'chapters': ['온라인'],
            'status': '진행 중', 'progress': '', 'due': '2026-10-16', 'dueNote': '',
            'issue': ['배너 제작 진행'], 'next': ['검토 요청'], 'decision': [], 'evidenceIds': ['E1', 'E2'],
            'roleFacts': [{'kind': 'owner', 'actor': 'UTEST1', 'sourceId': 'E1',
                           'quote': '<@UTEST1> 배너 제작 부탁드립니다.'},
                          {'kind': 'requester', 'actor': 'UTEST0', 'sourceId': 'E1',
                           'quote': '<@UTEST1> 배너 제작 부탁드립니다.'}],
            'completionFact': {'sourceId': '', 'quote': ''}, 'progressFact': {'sourceId': '', 'quote': ''}}

    def payload(self, active=None):
        return board.task_payloads([self.item], self.sources, active or [], self.cfg, self.start, self.end)[0]

    def test_previous_monday_0900_through_sunday_fractional_second(self):
        self.assertEqual(self.period, {'start': '2026-10-12', 'end': '2026-10-18'})
        self.assertEqual(self.start, dt.datetime(2026, 10, 12, 9, tzinfo=board.KST))
        self.assertEqual(self.end, dt.datetime(2026, 10, 19, tzinfo=board.KST))
        for now in (self.now, self.now + dt.timedelta(days=1)):
            self.assertEqual(board.report_period(now)[0], self.period)
        last = self.end.timestamp() - 0.1
        self.sources[self.key]['messages'][1]['ts'] = format(last, '.6f')
        self.payload()
        self.sources[self.key]['messages'][1]['ts'] = format(self.end.timestamp(), '.6f')
        with self.assertRaises(board.Stop):
            self.payload()

    def test_manual_never_publishes_even_with_flags_true(self):
        for event in ('workflow_dispatch', 'push', ''):
            self.assertFalse(board.publication_enabled({'GITHUB_EVENT_NAME': event, 'BOARD_ENABLED': 'true', 'PUBLISH': 'true'}))
        self.assertTrue(board.publication_enabled({'GITHUB_EVENT_NAME': 'schedule', 'BOARD_ENABLED': 'true', 'PUBLISH': 'true'}))
        self.assertFalse(board.publication_enabled({'GITHUB_EVENT_NAME': 'schedule', 'PUBLISH': 'true'}))
        api = board.BoardAPI('https://example.workers.dev', publish=False)
        with patch.object(api, 'token') as token:
            for operation in ('commit', 'notice-intent', 'notice-result'):
                with self.assertRaises(board.Stop):
                    api.call(operation, {})
            token.assert_not_called()

    def test_time_cutoffs_prevent_late_writes_and_wrong_day(self):
        board.ensure_write_window(self.now, self.monday)
        for now in (self.now.replace(hour=8, minute=30), self.now.replace(hour=7, minute=29), self.now + dt.timedelta(days=1)):
            with self.assertRaises(board.Stop):
                board.ensure_write_window(now, self.monday)
        with self.assertRaises(board.Stop):
            board.report_period(self.now + dt.timedelta(days=1), True)

    def test_pagination_exhausts_all_pages_and_rejects_incomplete_or_repeated_cursor(self):
        slack = board.Slack('test', 'user')
        with patch.object(slack, 'call', side_effect=[{'messages': [1], 'response_metadata': {'next_cursor': 'next'}},
                                                    {'messages': [2]}]) as call:
            self.assertEqual(slack.pages('conversations.history', {'channel': 'CTEST'}), [1, 2])
            self.assertEqual(call.call_args.args[1]['cursor'], 'next')
        for responses in ([{'messages': [], 'has_more': True}],
                          [{'messages': [], 'response_metadata': {'next_cursor': 'same'}}] * 2):
            with patch.object(slack, 'call', side_effect=responses), self.assertRaises(board.Stop):
                slack.pages('conversations.history', {})
        with patch.object(slack, 'call', return_value={'messages': [], 'response_metadata': {'next_cursor': 'next'}}), self.assertRaises(board.Stop):
            slack.pages('conversations.history', {}, max_pages=1)

    def test_user_collection_methods_and_dm_sources_are_blocked(self):
        slack = board.Slack('test', 'user')
        with patch.object(board, 'http_json') as http:
            for method in ('search.all', 'search.messages', 'conversations.open', 'users.conversations'):
                with self.assertRaises(board.Stop):
                    slack.call(method)
            with self.assertRaises(board.Stop):
                slack.call('chat.scheduleMessage', {}, write=True)
            http.assert_not_called()
        for info in ({'id': 'DTEST', 'is_im': True}, {'id': 'GTEST', 'is_mpim': True},
                     {'id': 'GTEST', 'is_private': True}):
            with self.assertRaises(board.Stop):
                board.check_channel(info)
        self.assertEqual(board.check_channel({'id': 'CTEST', 'is_private': False}), 'public_channel')

    def test_all_public_roots_scanned_for_fresh_replies_then_relevance_filtered(self):
        slack = MagicMock()
        old = stamp(1)
        current = stamp(15)
        def pages(method, params, key='messages'):
            if method == 'conversations.list':
                self.assertEqual(params['types'], 'public_channel')
                return [{'id': 'CTEST'}, {'id': 'CPROJECT'}]
            if method == 'conversations.history':
                self.assertNotIn('oldest', params)
                return [{'ts': old, 'text': '오래된 디자인 요청', 'reply_count': 1, 'latest_reply': current}]
            return [{'ts': old, 'user': 'UOTHER', 'text': '오래된 배너 디자인 요청'},
                    {'ts': current, 'user': 'UTEST2', 'text': '제가 배너 제작을 진행했습니다.'}]
        slack.pages.side_effect = pages
        slack.call.side_effect = lambda method, params: {'channel': {'id': params['channel'], 'is_private': False}}
        sources, coverage = board.collect_sources(slack, self.cfg, {'tasks': [], 'activeTasks': []}, self.start, self.end)
        self.assertEqual(len(sources), 2)
        self.assertTrue(coverage['complete'])
        self.assertTrue(all(row['current_ids'] for row in sources.values()))
        self.assertTrue(all(len(row['messages']) == 2 for row in sources.values()))

    def test_reference_parsing_prefers_original_thread_and_supports_store_fields(self):
        task = {'link': 'https://example.slack.com/archives/CTEST/p' + stamp(15).replace('.', '')
                        + '?thread_ts=' + stamp(1) + '&cid=CTEST',
                'automationEvidence': [{'channelId': 'CTEST', 'ts': stamp(15)}]}
        self.assertEqual(board.source_references(task), {('CTEST', stamp(1))})
        task = {'sourceLinks': ['https://example.slack.com/archives/CTEST/p' + stamp(1).replace('.', '')]}
        self.assertEqual(board.source_references(task), {('CTEST', stamp(1))})

    def test_direct_assignments_work_but_cc_and_invented_quotes_become_unknown(self):
        self.assertEqual(self.payload()['owner'], '테스트 담당자 1')
        self.sources[self.key]['messages'][0]['text'] = 'cc <@UTEST1> 배너 제작 현황 참고'
        self.item['roleFacts'][0]['quote'] = 'cc <@UTEST1> 배너 제작 현황 참고'
        self.item['due'] = ''
        payload = self.payload()
        self.assertEqual(payload['owner'], '확인 필요')
        self.assertEqual(payload['requester'], '확인 필요')

    def test_collaborators_need_direct_source_proof(self):
        self.item['collaborators'] = ['UCOLLAB']
        self.assertEqual(self.payload()['collaborators'], '')
        self.sources[self.key]['messages'][1]['text'] = '<@UCOLLAB> 배너 제작 협업 부탁드립니다.'
        self.item['roleFacts'].append({'kind': 'collaborator', 'actor': 'UCOLLAB', 'sourceId': 'E2',
                                      'quote': '<@UCOLLAB> 배너 제작 협업 부탁드립니다.'})
        self.assertEqual(self.payload()['collaborators'], '테스트 협업자')

    def test_completion_must_be_current_and_not_cherry_pick_pending_approval(self):
        self.item['status'] = '완료'
        self.item['completionFact'] = {'sourceId': 'E2', 'quote': '전체 게시 완료했습니다.'}
        self.sources[self.key]['messages'][1]['text'] = '전체 게시 완료했습니다.'
        self.assertEqual(self.payload()['status'], '완료')
        self.sources[self.key]['messages'][1]['text'] = '전체 게시 완료했습니다. 승인 대기'
        with self.assertRaises(board.Stop):
            self.payload()
        self.sources[self.key]['messages'][1]['text'] = '전체 게시 완료했습니다.'
        self.sources[self.key]['messages'][1]['ts'] = stamp(1)
        self.item['evidenceIds'] = ['E1']
        with self.assertRaises(board.Stop):
            self.payload()

    def test_progress_cannot_be_inferred(self):
        self.item['progress'] = '80'
        with self.assertRaises(board.Stop):
            self.payload()
        self.item['progressFact'] = {'sourceId': 'E2', 'quote': '진행률 80%입니다.'}
        self.assertEqual(self.payload()['progress'], '80')
        self.item['progress'] = '90'
        with self.assertRaises(board.Stop):
            self.payload()

    def test_existing_task_matching_requires_same_thread_and_same_deliverable_title(self):
        self.item['sourceTaskId'] = 'old-task'
        old = {'id': 'old-task', 'title': self.item['title'], 'link': 'https://example.slack.com/archives/CTEST/p' + stamp(13).replace('.', '')}
        self.assertEqual(self.payload([old])['sourceTaskId'], 'old-task')
        old['link'] = 'https://example.slack.com/archives/CTEST/p' + stamp(1).replace('.', '')
        with self.assertRaises(board.Stop):
            self.payload([old])
        old['link'] = 'https://example.slack.com/archives/CTEST/p' + stamp(13).replace('.', '')
        self.item['title'] = '별개의 새 산출물'
        with self.assertRaises(board.Stop):
            self.payload([old])

    def test_concise_fields_and_sensitive_sources(self):
        self.item['issue'] = ['첫 항목', '둘째 항목', '셋째 항목', '넷째 항목']
        with self.assertRaises(board.Stop):
            self.payload()
        self.assertFalse(board.visible_message({'text': 'API_KEY=private-value', 'user': 'UTEST1'}, self.cfg))
        self.assertFalse(board.visible_message({'text': '휴가 신청합니다.', 'user': 'UTEST1'}, self.cfg))
        self.assertFalse(board.visible_message({'text': '디자인 업무', 'bot_id': 'BBOT'}, self.cfg))

    def notice_state(self, state='none'):
        return {'status': 'committed', 'runId': '123', 'period': self.period, 'notice': {'state': state}}

    def notice_clients(self):
        api = MagicMock()
        api.base = 'https://example.workers.dev'
        api.call.return_value = {'shouldSend': True}
        bot = MagicMock()
        bot.pages.return_value = []
        bot.call.return_value = {'ok': True, 'scheduled_message_id': 'QTEST', 'channel': 'CTEST',
                                'post_at': int(self.now.replace(hour=9).timestamp())}
        return api, bot

    @patch.dict(os.environ, {'GITHUB_RUN_ID': '456'})
    def test_notice_intent_precedes_slack_and_retry_execution_identity_is_separate(self):
        api, bot = self.notice_clients()
        calls = []
        api.call.side_effect = lambda operation, data: calls.append(operation) or {'shouldSend': True}
        receipt = bot.call.return_value
        bot.call.side_effect = lambda *args, **kwargs: calls.append(args[0]) or receipt
        self.assertEqual(board.schedule_notice(api, bot, self.cfg, self.notice_state(), self.monday, self.now), 'scheduled')
        self.assertEqual(calls, ['notice-intent', 'chat.scheduleMessage', 'notice-result'])
        for call in api.call.call_args_list:
            self.assertEqual(call.args[1]['runId'], '123')
            self.assertEqual(call.args[1]['executionRunId'], '456')
        self.assertNotIn('metadata', bot.call.call_args.args[1])

    @patch.dict(os.environ, {'GITHUB_RUN_ID': '456'})
    def test_notice_ambiguous_result_is_recorded_once_and_never_retried(self):
        api, bot = self.notice_clients()
        bot.call.side_effect = board.Stop('Uncertain')
        with self.assertRaises(board.Stop):
            board.schedule_notice(api, bot, self.cfg, self.notice_state(), self.monday, self.now)
        self.assertEqual(bot.call.call_count, 1)
        self.assertEqual(api.call.call_args.args[1]['outcome'], 'unknown')
        for state in ('pending', 'unknown', 'rejected'):
            api, bot = self.notice_clients()
            with self.assertRaises(board.Stop):
                board.schedule_notice(api, bot, self.cfg, self.notice_state(state), self.monday, self.now)
            bot.call.assert_not_called()
        api, bot = self.notice_clients()
        self.assertEqual(board.schedule_notice(api, bot, self.cfg, self.notice_state('accepted'), self.monday, self.now), 'already_accepted')
        bot.call.assert_not_called()

    @patch.dict(os.environ, {'GITHUB_RUN_ID': '456'})
    def test_existing_scheduled_receipt_is_reconciled_without_second_message(self):
        api, bot = self.notice_clients()
        text = board.notice_text(self.cfg, self.period, api.base)
        bot.pages.side_effect = [[{'id': 'QEXISTING', 'post_at': int(self.now.replace(hour=9).timestamp()), 'text': text}], []]
        self.assertEqual(board.schedule_notice(api, bot, self.cfg, self.notice_state(), self.monday, self.now), 'existing_receipt_recorded')
        bot.call.assert_not_called()
        self.assertEqual(api.call.call_args.args[1]['scheduledMessageId'], 'QEXISTING')

    @patch.dict(os.environ, {'GITHUB_RUN_ID': '456'})
    def test_posted_notice_and_time_cutoff_never_create_new_schedule(self):
        api, bot = self.notice_clients()
        text = board.notice_text(self.cfg, self.period, api.base)
        bot.pages.side_effect = [[], [{'ts': stamp(19, 7), 'text': text, 'user': 'UBOT'}]]
        with self.assertRaises(board.Stop):
            board.schedule_notice(api, bot, self.cfg, self.notice_state(), self.monday, self.now)
        api.call.assert_not_called()
        bot.call.assert_not_called()
        api, bot = self.notice_clients()
        with self.assertRaises(board.Stop):
            board.schedule_notice(api, bot, self.cfg, self.notice_state(), self.monday, self.now.replace(minute=58))
        api.call.assert_not_called()

    def test_preflight_needs_neither_user_token_nor_openai_and_logs_no_source(self):
        env = {'BOARD_CONFIG': json.dumps(self.cfg), 'WORKBOARD_URL': 'https://example.workers.dev',
               'SLACK_BOT_TOKEN': 'synthetic', 'BOARD_PHASE': 'preflight', 'GITHUB_EVENT_NAME': 'workflow_dispatch'}
        api = MagicMock()
        api.call.side_effect = [{'revision': 'rev', 'meta': {'defaultWeek': '2026-10-12'},
                                'tasks': [{'title': 'PRIVATE_SOURCE_CANARY'}], 'activeTasks': []},
                               {'status': 'not_found'}]
        bot = MagicMock()
        bot.call.side_effect = [{'team_id': 'TTEST', 'user_id': 'UBOT'}, {'ok': True, 'messages': [{'text': 'PRIVATE_SOURCE_CANARY'}]}]
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch.object(board, 'BoardAPI', return_value=api), \
                patch.object(board, 'Slack', return_value=bot), patch.object(board, 'summarize') as model, \
                contextlib.redirect_stdout(output):
            board.execute(self.now)
        self.assertNotIn('PRIVATE_SOURCE_CANARY', output.getvalue())
        self.assertIn('Task total: 1', output.getvalue())
        self.assertEqual([c.args[0] for c in api.call.call_args_list], ['snapshot', 'status'])
        self.assertEqual([c.args[0] for c in bot.call.call_args_list], ['auth.test', 'conversations.history'])
        model.assert_not_called()

    def test_validate_manual_cannot_commit_even_with_true_publish_env(self):
        env = {'BOARD_CONFIG': json.dumps(self.cfg), 'WORKBOARD_URL': 'https://example.workers.dev',
            'SLACK_BOT_TOKEN': 'synthetic', 'SLACK_USER_TOKEN': 'synthetic-user', 'OPENAI_API_KEY': 'synthetic-api',
            'BOARD_PHASE': 'validate', 'GITHUB_EVENT_NAME': 'workflow_dispatch', 'BOARD_ENABLED': 'true', 'PUBLISH': 'true'}
        api = MagicMock()
        api.call.side_effect = [{'status': 'not_found'}, {'revision': 'r', 'tasks': [], 'activeTasks': []}]
        user, bot = MagicMock(), MagicMock()
        user.call.return_value = {'team_id': 'TTEST', 'user_id': 'UAUTH'}
        bot.call.return_value = {'team_id': 'TTEST', 'user_id': 'UBOT'}
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch.object(board, 'BoardAPI', return_value=api) as ctor, \
                patch.object(board, 'Slack', side_effect=[bot, user]), \
                patch.object(board, 'collect_sources', return_value=(self.sources, {'complete': True})), \
                patch.object(board, 'summarize', return_value=[self.item]), contextlib.redirect_stdout(output):
            board.execute(self.now)
        self.assertFalse(ctor.call_args.args[1])
        self.assertEqual([c.args[0] for c in api.call.call_args_list], ['status', 'snapshot'])
        self.assertIn('no board or Slack writes', output.getvalue())

    def test_oidc_audience_and_redirect_guard(self):
        api = board.BoardAPI('https://example.workers.dev')
        env = {'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://test.actions.githubusercontent.com/idtoken?x=1',
               'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'synthetic-token'}
        with patch.dict(os.environ, env), patch.object(board, 'http_json', return_value={'value': 'aaa.bbb.ccc'}) as request:
            self.assertEqual(api.token(), 'aaa.bbb.ccc')
            self.assertIn('audience=https%3A%2F%2Fexample.workers.dev%2Fautomation', request.call_args.args[0])
        req = board.urllib.request.Request('https://slack.com/api/auth.test')
        with self.assertRaises(urllib.error.HTTPError):
            board.NoRedirect().redirect_request(req, None, 302, '', {}, 'https://untrusted.example')

    def test_server_error_is_ambiguous_without_source_logging_or_write_retry(self):
        error = urllib.error.HTTPError('https://slack.com/api/chat.scheduleMessage', 500, 'PRIVATE_SOURCE_CANARY', {}, None)
        opener = MagicMock()
        opener.open.side_effect = error
        with patch.object(board.urllib.request, 'build_opener', return_value=opener), self.assertRaises(board.Stop) as stopped:
            board.http_json('https://slack.com/api/chat.scheduleMessage', 'synthetic', {'text': 'PRIVATE_SOURCE_CANARY'}, 'Slack')
        self.assertNotIsInstance(stopped.exception, board.Rejected)
        self.assertNotIn('PRIVATE_SOURCE_CANARY', str(stopped.exception))
        self.assertEqual(opener.open.call_count, 1)

    @patch.dict(os.environ, {'GITHUB_RUN_ID': '456'})
    def test_notice_cutoff_is_rechecked_after_slow_receipt_reads(self):
        api, bot = self.notice_clients()
        with patch.object(board.time, 'monotonic', side_effect=[0, 61]), self.assertRaises(board.Stop):
            board.schedule_notice(api, bot, self.cfg, self.notice_state(), self.monday, self.now.replace(minute=57))
        api.call.assert_not_called()
        bot.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
