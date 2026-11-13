import datetime as dt
import unittest
from unittest.mock import patch
import dashboard_report as report


NOW = dt.datetime(2026, 11, 13, 17, tzinfo=report.KST)


def task(id='one', **fields):
    return dict(id=id, title='합성 테스트 시안', status='진행 중', owner='테스트 담당', **fields)


def snapshot(tasks):
    return {'meta': {'daily': {'sourceCutoff': '2026-11-13T06:59:59+09:00'}}, 'tasks': tasks}


class DashboardReportTests(unittest.TestCase):
    def render(self, rows):
        return report.render(snapshot(rows), NOW, 'https://board.example')

    def test_completed_date_required_for_weekly_result(self):
        rows = [dict(task(), status='완료')]
        intro, parts = self.render(rows)
        self.assertIn('금주 완료 확인 0건', intro)
        self.assertIn('금주 완료 실적 집계 제외', parts[0])

    def test_prior_completion_excluded_and_current_archive_retained(self):
        rows = [dict(task('old'), status='완료', completedDate='2026-11-06'),
                dict(task('current'), status='완료', completedDate='2026-11-12', archived=True)]
        selected = report.select_tasks(snapshot(rows), dt.date(2026, 11, 9), NOW.date())
        self.assertEqual([t['id'] for t in selected], ['current'])

    def test_server_identity_and_manual_fields_win(self):
        data = snapshot([task('duplicate')])
        data['activeTasks'] = [dict(task('reviewed'), owner='사람이 확인한 담당', issue='확인한 내용')]
        intro, parts = report.render(data, NOW, 'https://board.example')
        self.assertIn('미완료 1건', intro)
        self.assertIn('사람이 확인한 담당', parts[0])

    def test_followup_without_date_is_not_confirmed_next_week(self):
        intro, _ = self.render([task(next='최종 문구 확인')])
        self.assertIn('차주 실행 여부 확인 필요', intro)
        self.assertNotIn('11/16 마감', intro)

    def test_blockers_and_decisions(self):
        intro, parts = self.render([dict(task(), status='자료 대기', decision='문구 확정 요청')])
        self.assertIn('미결·확인 필요 1건', intro)
        self.assertIn('문구 확정 요청', intro)

    def test_deleted_not_reported(self):
        intro, parts = self.render([task(deletedAt='2026-11-13')])
        self.assertIn('등록된 업무 없음', parts[0])

    def test_stale_cutoff_stops(self):
        data = snapshot([task()])
        data['meta']['daily']['sourceCutoff'] = '2026-11-06T07:00:00+09:00'
        with self.assertRaises(report.Stop):
            report.render(data, NOW, 'https://board.example')

    def test_split_preserves_all_tasks(self):
        rows = [task(str(n), issue=('가' * 499), next='나' * 499) for n in range(50)]
        intro, parts = self.render(rows)
        self.assertGreater(len(parts), 1)
        self.assertEqual(sum(p.count('담당:') for p in parts), 50)
        self.assertTrue(all(len(p) < 12000 for p in parts))

    def test_slack_mentions_in_text_are_escaped(self):
        _, parts = self.render([task(issue='<!channel> <@U123>')])
        self.assertNotIn('<!channel>', parts[0])

    def test_manual_publish_request_cannot_send(self):
        with patch.dict(report.os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch',
                       'PUBLISH': 'true', 'FRIDAY_REPORTS_ENABLED': 'true',
                       'WORKBOARD_URL': 'https://board.example'}, clear=True), \
             patch.object(report.BoardAPI, 'call', return_value=snapshot([task()])), \
             patch.object(report, 'send_report') as send:
            report.main()
            send.assert_not_called()

    def test_legacy_report_prevents_duplicate(self):
        root = {'metadata': {'event_payload': {'report_key': NOW.date().isoformat()}}}
        with patch.object(report.weekly, 'pages', return_value=[root]), \
             patch.object(report.weekly, 'slack') as slack:
            report.send_report('intro', ['detail'], NOW.date())
            slack.assert_not_called()


if __name__ == '__main__':
    unittest.main()
