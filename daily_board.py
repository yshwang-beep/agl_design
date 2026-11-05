"""Daily 07:00 KST collection and explicitly scoped historical previews."""
import datetime as dt
import os
import re
import sys
import time
import copy

import board_weekly as board


class AsOfSlack(board.Slack):
    """Reuse channel reads for four cutoffs, never later text in an earlier view."""
    def __init__(self, token, latest):
        super().__init__(token, 'user')
        self.latest, self.page_cache, self.info_cache = latest, {}, {}

    def call(self, method, params=None, write=False):
        if not write and method in {'auth.test', 'conversations.info'}:
            key = (method, str(sorted((params or {}).items())))
            if key not in self.info_cache:
                self.info_cache[key] = super().call(method, params)
            return copy.deepcopy(self.info_cache[key])
        return super().call(method, params, write)

    def pages(self, method, params, key='messages', max_pages=1000):
        requested = params.get('latest')
        maximum = dict(params)
        if requested is not None:
            if float(requested) > float(self.latest):
                raise board.Stop('Historical source cutoff exceeds the shared read cutoff.')
            maximum['latest'] = self.latest
        cache_key = (method, str(sorted(maximum.items())), key, max_pages)
        if cache_key not in self.page_cache:
            self.page_cache[cache_key] = super().pages(method, maximum, key, max_pages)
        rows = self.page_cache[cache_key]
        if requested is not None:
            rows = [row for row in rows if float(row['ts']) <= float(requested)]
        return copy.deepcopy(rows)


class DailyAPI(board.BoardAPI):
    def __init__(self, base, date, publish=False, backfill=False):
        super().__init__(base, publish)
        self.date, self.backfill = date, backfill

    def call(self, operation, data=None):
        names = {'snapshot': 'snapshot', 'status': 'daily-status',
                 'baseline': 'daily-baseline', 'capabilities': 'daily-capabilities', 'commit': 'daily-backfill' if self.backfill else 'daily-commit',
                 'notice-intent': 'daily-notice-intent', 'notice-result': 'daily-notice-result'}
        if operation not in names:
            raise board.Stop('Unknown daily operation.')
        if operation not in {'snapshot', 'status', 'baseline', 'capabilities'} and not self.publish:
            raise board.Stop('Read-only daily validation cannot write.')
        payload = dict(data or {}, date=self.date)
        value = board.http_json(self.base + '/api/automation/' + names[operation], self.token(), payload, 'Workboard')
        if not isinstance(value, dict) or value.get('error'):
            raise board.Stop('Daily workboard operation rejected.')
        return value


def window(date, snapshot=None, backfill=False):
    end = dt.datetime.combine(date, dt.time(7), board.KST)
    last = (snapshot or {}).get('meta', {}).get('daily', {}).get('sourceCutoff')
    start = (dt.datetime.fromisoformat(last) + dt.timedelta(seconds=1)) if last and not backfill else end - dt.timedelta(days=7)
    if start >= end:
        raise board.Stop('Daily cutoff must advance.')
    return start, end


def ensure_window(now, date):
    if now.date() != date or not dt.time(7) <= now.time() < dt.time(8, 30):
        raise board.Stop('Daily collection writes are limited to 07:00–08:30 KST.')


def draft(sources, active, cfg, period, start, end):
    repair = None
    for _ in range(3):
        items = board.summarize(sources, active, cfg, period, repair)
        tasks, failures = board.validate_draft(items, sources, active, cfg, start, end)
        if not failures:
            return tasks, ''
        repair = {'failures': failures, 'previous_items': items}
    tasks, review, deferred = board.reviewed_fallback(items, sources, active, cfg, start, end)
    note = ('원문 재확인 필요 ' + str(review) + '건, 신규 반영 보류 ' + str(deferred) + '건입니다.') if review or deferred else ''
    return tasks, note


def collapse_daily_tasks(tasks):
    """One latest evidenced draft per exact existing ID or new deliverable identity."""
    grouped = {}
    for task in tasks:
        key = ('existing', task['sourceTaskId']) if task.get('sourceTaskId') else ('new', ' '.join(task['title'].split()), task.get('link') or task['evidence'][0]['url'])
        prior = grouped.get(key)
        if prior is None:
            grouped[key] = task
            continue
        latest = max((prior, task), key=lambda row: max(float(e['ts']) for e in row['evidence']))
        evidence = {(e['channelId'], e['ts']): e for row in (prior, task) for e in row['evidence']}
        grouped[key] = dict(latest, evidence=sorted(evidence.values(), key=lambda e: float(e['ts']))[-200:],
                            reviewed='no', verification='여러 근거의 최신 내용 기준 · 원문 확인 필요')
    return list(grouped.values())


def execute(now=None):
    now = now or dt.datetime.now(board.KST)
    cfg = board.config_from_env()
    phase = os.environ.get('BOARD_PHASE', 'preflight')
    if phase not in {'preflight', 'validate', 'backfill'}:
        raise board.Stop('Unknown daily phase.')
    backfill = phase == 'backfill'
    publish = (os.environ.get('BOARD_ENABLED') == 'true' and os.environ.get('PUBLISH') == 'true'
               and (os.environ.get('GITHUB_EVENT_NAME') == 'schedule' or backfill))
    if backfill:
        values = os.environ.get('BACKFILL_DATES', '').split(',')
        if not 1 <= len(values) <= 4 or len(set(values)) != len(values):
            raise board.Stop('Select one to four distinct backfill dates.')
        try:
            dates = sorted((dt.date.fromisoformat(v) for v in values), reverse=True)
        except ValueError:
            raise board.Stop('Invalid backfill dates.') from None
        if any(d > now.date() or d < now.date() - dt.timedelta(days=14) for d in dates):
            raise board.Stop('Backfill is limited to the last fourteen days.')
    else:
        dates = [now.date()]
    # Context is bounded by the exact daily cutoff, not a calendar week.
    board.BOARD_RULES = board.BOARD_RULES.replace('디자인팀 주간 업무판', '디자인팀 일별 업무판') + '\n현재 context.period와 원문 기준시각을 적용한다. 이전 보고서나 미래 날짜의 내용으로 과거 상태를 추정하지 않는다.'
    bot = board.Slack(os.environ['SLACK_BOT_TOKEN'], 'bot', publish=publish and not backfill)
    if backfill and publish:
        permission_api = DailyAPI(os.environ['WORKBOARD_URL'], dates[0].isoformat())
        for attempt in range(60):
            access = permission_api.call('capabilities')
            if access.get('canBackfill') and all(d.isoformat() in access.get('dates', []) for d in dates):
                break
            if attempt == 0:
                print('Waiting for the exact-run historical-record grant; no writes or collection yet.', flush=True)
            time.sleep(10)
        else:
            raise board.Stop('Historical-record grant was not provisioned.')
    shared_user = AsOfSlack(os.environ['SLACK_USER_TOKEN'], format(dt.datetime.combine(max(dates), dt.time(7), board.KST).timestamp() - .000001, '.6f')) if backfill else None
    for date in dates:
        date_string = date.isoformat()
        api = DailyAPI(os.environ['WORKBOARD_URL'], date_string, publish, backfill)
        if phase == 'preflight':
            board.preflight(cfg, api, bot, {})
            return
        identity = bot.call('auth.test')
        if identity.get('team_id') != cfg['team_id'] or identity.get('user_id') != cfg['bot_user_id']:
            raise board.Stop('Unexpected bot identity.')
        if publish and not backfill:
            ensure_window(now, date)
        existing = api.call('status')
        if publish and existing.get('status') == 'committed':
            if not backfill and date.weekday() == 0:
                board.schedule_notice(api, bot, cfg, existing, date, dt.datetime.now(board.KST))
            print('PASS: Existing daily record reused: ' + date_string, flush=True)
            continue
        snapshot = api.call('baseline' if backfill else 'snapshot')
        if backfill and snapshot.get('pendingCommit'):
            result = api.call('commit', snapshot['pendingCommit'])
            verified = api.call('status')
            if verified.get('status') != 'committed' or verified.get('revision') != result.get('revision'):
                raise board.Stop('Resumed historical record readback failed.')
            print('PASS: Daily record saved and verified: ' + date_string + '; rows=' + str(verified['rowCount']), flush=True)
            continue
        start, end = window(date, snapshot, backfill)
        active = snapshot['activeTasks']
        user = shared_user or board.Slack(os.environ['SLACK_USER_TOKEN'], 'user')
        identity = user.call('auth.test')
        if identity.get('team_id') != cfg['team_id'] or identity.get('bot_id'):
            raise board.Stop('Unexpected collection identity.')
        sources, coverage = board.collect_sources(user, cfg, snapshot, start, end)
        period = {'start': start.date().isoformat(), 'end': end.date().isoformat()}
        tasks, note = draft(sources, active, cfg, period, start, end)
        tasks = collapse_daily_tasks(tasks)
        if not publish:
            print('PASS: Daily draft validated without writes: ' + date_string + '; tasks=' + str(len(tasks)), flush=True)
            continue
        if not backfill:
            ensure_window(dt.datetime.now(board.KST), date)
        run_id = os.environ.get('GITHUB_RUN_ID', '')
        if not re.fullmatch(r'\d+', run_id):
            raise board.Stop('Missing GitHub run identity.')
        result = api.call('commit', {'runId': run_id, 'expectedRevision': snapshot['revision'],
                                    'tasks': tasks, 'coverage': coverage, 'sourceStart': start.isoformat(),
                                    'sourceCutoff': (end - dt.timedelta(seconds=1)).isoformat()})
        verified = api.call('status')
        if verified.get('status') != 'committed' or verified.get('revision') != result.get('revision') or verified.get('runId') != result.get('runId'):
            raise board.Stop('Daily record readback failed.')
        if not backfill and date.weekday() == 0:
            board.schedule_notice(api, bot, cfg, verified, date, dt.datetime.now(board.KST), review_note=note)
        print('PASS: Daily record saved and verified: ' + date_string + '; rows=' + str(verified['rowCount']), flush=True)


if __name__ == '__main__':
    try:
        execute()
    except board.Stop as error:
        print('STOP: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('STOP: Daily processing failed; no private details logged.', file=sys.stderr)
        sys.exit(1)
