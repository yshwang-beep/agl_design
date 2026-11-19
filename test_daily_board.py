import datetime as dt
import unittest
from unittest.mock import patch
import daily_board as daily


class DailyTests(unittest.TestCase):
    def test_receipts_reuse_only_identical_sources_and_committed_baselines(self):
        import copy
        key='CTEST:1795000000.000000'
        source={'channel_id':'CTEST','thread_ts':'1795000000.000000',
                'messages':[{'evidence_id':'E1','ts':'1795000000.000000','user':'U1','text':'원문'}], 'current_ids':['E1']}
        cfg={'designers':[]}; end=dt.datetime(2026,11,19,7,tzinfo=daily.board.KST)
        active=[{'id':'T1','title':'업무','link':'https://example.slack.com/archives/CTEST/p1795000000000000','issue':'원문 유지'}]
        receipts={daily.digest(key):{'source':daily.analysis_signature(source,cfg),
            'baseline':daily.source_baseline(key,source,active),'cutoff':(end-dt.timedelta(days=1)).isoformat()}}
        self.assertEqual(daily.uncached_sources({key:source},active,cfg,receipts,end),{})
        for changed in ['new_reply','edited_text','deleted_message']:
            new=copy.deepcopy(source)
            if changed=='new_reply': new['messages'].append({'evidence_id':'E2','ts':'1795000001.000000','user':'U1','text':'11/23 추가 공유'})
            elif changed=='edited_text': new['messages'][0]['text']='수정된 내용'
            else: new['messages']=[]
            self.assertEqual(list(daily.uncached_sources({key:new},active,cfg,receipts,end)),[key])
        for altered in [[{**active[0],'issue':'수동 변경'}],[]]:
            self.assertEqual(list(daily.uncached_sources({key:source},altered,cfg,receipts,end)),[key])
        for age in [7,-1]:
            receipt=copy.deepcopy(receipts);receipt[daily.digest(key)]['cutoff']=(end-dt.timedelta(days=age)).isoformat()
            self.assertTrue(daily.uncached_sources({key:source},active,cfg,receipt,end))
        with patch.dict('os.environ',{'OPENAI_MODEL':'different-model'}):
            self.assertTrue(daily.uncached_sources({key:source},active,cfg,receipts,end))
        self.assertTrue(daily.uncached_sources({key:source},active,{'designers':[],'source_policy':'new'},receipts,end))

    def test_receipts_do_not_reuse_sensitive_edited_task_or_changed_evidence(self):
        # Cache identity must still notice private manual values; only their hash is stored.
        key='CTEST:1795000000.000000'; source={'channel_id':'CTEST','thread_ts':'1795000000.000000','messages':[]}
        active=[{'id':'T1','link':'https://example.slack.com/archives/CTEST/p1795000000000000','issue':'휴가 기존값'}]
        self.assertNotEqual(daily.source_baseline(key,source,active),daily.source_baseline(key,source,[{**active[0],'issue':'휴가 변경값'}]))

    def test_cache_write_waits_for_committed_revision_and_contains_only_hashes(self):
        from unittest.mock import MagicMock
        api=MagicMock();api.call.return_value={'revision':'changed','activeTasks':[]}
        end=dt.datetime(2026,11,19,7,tzinfo=daily.board.KST)
        daily.save_analysis_receipts(api,{}, {},end,'expected')
        self.assertEqual(api.call.call_count,1)

    def test_readonly_validation_can_repeat_after_scheduled_cutoff(self):
        now=dt.datetime(2026,11,11,12,10,tzinfo=daily.board.KST)
        start,end=daily.validation_window(now)
        self.assertEqual(end,now)
        self.assertEqual(start,now-dt.timedelta(days=14))
        with self.assertRaises(daily.board.Stop):
            daily.window(now.date(),{'meta':{'daily':{'sourceCutoff':'2026-11-11T06:59:59+09:00'}}})
        self.assertGreater(end,dt.datetime(2026,11,11,7,tzinfo=daily.board.KST))

    def test_incremental_days_and_monday_full_review_preserve_cursor_and_backfill(self):
        start,end=daily.window(dt.date(2026,11,11),{'meta':{'daily':{'sourceCutoff':'2026-11-10T06:59:59+09:00'}}})
        self.assertEqual(start.isoformat(),'2026-11-10T07:00:00+09:00')
        self.assertEqual(daily.review_start(start,end), start)
        monday=end+dt.timedelta(days=5)
        monday_start=monday-dt.timedelta(days=1)
        self.assertEqual(daily.review_start(monday_start,monday),monday-dt.timedelta(days=14))
        self.assertEqual(daily.review_start(monday_start,monday,backfill=True),monday_start)
        for offset in range(1,7):
            cutoff=monday+dt.timedelta(days=offset)
            self.assertEqual(daily.review_start(cutoff-dt.timedelta(days=1),cutoff),cutoff-dt.timedelta(days=1))
        self.assertEqual(daily.review_start(start,end,backfill=True),start)
        older=start-dt.timedelta(days=30)
        self.assertEqual(daily.review_start(older,end),older)

    def test_repair_reuses_passed_sources_and_rechecks_the_complete_failed_thread(self):
        sources={'A': {'messages': ['entire A']}, 'B': {'messages': ['entire B']}}
        passed={'sourceKey':'A','title':'kept'}
        failed={'sourceKey':'B','title':'bad'}
        fixed={'sourceKey':'B','title':'fixed'}
        errors=[{'sourceKey':'B','item_index':1,'failure':'bad evidence'}]
        with patch.object(daily.board,'summarize',side_effect=[[passed,failed],[fixed]]) as summarize, patch.object(daily.board,'validate_draft',side_effect=[(['valid A'],errors),(['valid A','valid B'],[])]) as validate:
            tasks,note=daily.draft(sources,[],{}, {},None,None)
        self.assertEqual(tasks,['valid A','valid B'])
        self.assertEqual(note,'')
        self.assertEqual(summarize.call_count,2)
        self.assertEqual(summarize.call_args.args[0],{'B':sources['B']})
        self.assertEqual(summarize.call_args.args[4]['previous_items'],[failed])
        self.assertEqual(validate.call_args.args[0],[passed,fixed])
        self.assertEqual(validate.call_args.args[1],sources)

    def test_persistent_failed_source_uses_existing_fallback_after_three_attempts(self):
        sources={'A':{},'B':{}}
        passed={'sourceKey':'A','title':'kept'}
        failed={'sourceKey':'B','title':'bad'}
        errors=[{'sourceKey':'B','item_index':1,'failure':'bad evidence'}]
        with patch.object(daily.board,'summarize',side_effect=[[passed,failed],[failed],[failed]]) as summarize, patch.object(daily.board,'validate_draft',return_value=([],errors)), patch.object(daily.board,'reviewed_fallback',return_value=(['safe'],1,0)) as fallback:
            tasks,note=daily.draft(sources,[],{},{},None,None)
        self.assertEqual(tasks,['safe'])
        self.assertEqual(summarize.call_count,3)
        self.assertTrue(all(list(call.args[0])==['B'] for call in summarize.call_args_list[1:]))
        self.assertEqual(fallback.call_args.args[0],[passed,failed])
        self.assertIn('1건',note)

    def test_repair_cannot_introduce_an_unrelated_source(self):
        with patch.object(daily.board,'summarize',return_value=[{'sourceKey':'unknown'}]), self.assertRaises(daily.board.Stop):
            daily.draft({'A':{}},[],{},{},None,None)

    def test_no_new_sources_requires_no_ai_requests(self):
        with patch.object(daily.board,'http_json') as request:
            self.assertEqual(daily.draft({},[],{'designers':[]},{},None,None),([],''))
            request.assert_not_called()

    def test_shared_historical_reads_filter_future_messages_and_fetch_once(self):
        client=daily.AsOfSlack('synthetic', '200.000000')
        rows=[{'ts':'100.000000','text':'before'},{'ts':'150.000000','text':'later'}]
        with patch.object(daily.board.Slack,'pages',return_value=rows) as read:
            old=client.pages('conversations.history',{'channel':'CTEST','latest':'120.000000'})
            new=client.pages('conversations.history',{'channel':'CTEST','latest':'180.000000'})
            self.assertEqual([m['text'] for m in old],['before'])
            self.assertEqual(len(new),2)
            read.assert_called_once()
            self.assertEqual(read.call_args.args[1]['latest'],'200.000000')
            old[0]['text']='changed'
            self.assertEqual(client.pages('conversations.history',{'channel':'CTEST','latest':'120.000000'})[0]['text'],'before')
        with self.assertRaises(daily.board.Stop):
            client.pages('conversations.history',{'latest':'201.000000'})

    def test_duplicate_existing_sources_use_latest_facts_and_union_evidence(self):
        first={'sourceTaskId':'original','title':'same','status':'진행 중','evidence':[{'channelId':'C123','ts':'100.000000','url':'old'}]}
        last={**first,'status':'완료','evidence':[{'channelId':'C123','ts':'200.000000','url':'new'}]}
        rows=daily.collapse_daily_tasks([last,first])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['status'],'완료')
        self.assertEqual(len(rows[0]['evidence']),2)
        self.assertEqual(rows[0]['reviewed'],'no')
        self.assertIn('원문 확인 필요',rows[0]['verification'])

    def test_separate_weeks_and_phases_cannot_silently_collapse(self):
        for titles in [('인스타그램 11월 3주차','인스타그램 11월 4주차'),('모델 이미지 1차 제작','모델 이미지 2차 제작'),('브랜드 배너 제작','브랜드 썸네일 제작')]:
            rows=[{'sourceTaskId':'existing','title':title,'evidence':[{'channelId':'CTEST','ts':'100.000000','url':'test'}]} for title in titles]
            with self.subTest(titles=titles),self.assertRaises(daily.board.Stop):
                daily.collapse_daily_tasks(rows)

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
            [daily.ensure_window(dt.datetime.combine(date, time, daily.board.KST), date) for time in [dt.time(7), dt.time(8, 30), dt.time(10, 35), dt.time(13, 20), dt.time(23, 59)]]
            for time in [dt.time(6, 59), dt.time(0)]:
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
