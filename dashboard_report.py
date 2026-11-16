"""Friday report from saved workboard data; no AI or board writes."""
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import weekly_report as weekly
from board_weekly import BoardAPI, Stop

KST = weekly.KST
MARKER = 'design_dashboard_weekly_v1'
BLOCKED = {'승인 대기', '자료 대기', '검토 대기', '일정 조율', '일정 지연', '보류', '확인 필요'}


def clean(value, limit=500):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if len(text) > limit:
        text = text[:limit] + '… (전체 내용은 대시보드 참조)'
    return html.escape(text, quote=False).replace('*', '＊').replace('`', '｀')


def date(value):
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def identity(task):
    return str(task.get('originalTaskId') or task.get('liveTaskId') or task.get('id', '')).removeprefix('daily:')


def select_tasks(snapshot, monday, day):
    if not isinstance(snapshot.get('tasks'), list):
        raise Stop('Workboard snapshot is incomplete.')
    # The server projection preserves reviewed identity/ownership and human edits.
    active = snapshot.get('activeTasks', [t for t in snapshot['tasks'] if not t.get('archived')])
    chosen = {identity(t): t for t in active if not t.get('deletedAt')}
    for task in snapshot['tasks']:
        finished = date(task.get('completedDate'))
        if task.get('status') == '완료' and finished and monday <= finished <= day and not task.get('deletedAt'):
            chosen.setdefault(identity(task), task)
    result = []
    for task in chosen.values():
        if not task.get('title') or not identity(task):
            raise Stop('A workboard task is missing its identity or title.')
        finished = date(task.get('completedDate'))
        if task.get('status') == '완료' and finished and not monday <= finished <= day:
            continue
        result.append(task)
    return sorted(result, key=lambda t: (t.get('chapter', ''), t.get('due') or '9999', t['title']))


def reference(task):
    value = task.get('link', '')
    parsed = urlsplit(value)
    if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not re.search(r'[<>|\s]', value):
        return '\n↳ <' + html.escape(value, quote=False) + '|업무 원문>'
    return ''


def card(task):
    status = task.get('status') or '확인 필요'
    lines = ['*' + clean(task['title'], 160) + '* · ' + clean(status),
             '담당: ' + clean(task.get('owner') or '확인 필요', 120)
             + ' ｜ 마감: ' + clean(task.get('due') or '미정', 40)]
    if status == '완료':
        lines.append('• 완료일: ' + clean(task.get('completedDate') or '미확인 — 금주 완료 실적 집계 제외'))
        lines.append('• 완료 범위: ' + clean(task.get('completionScope') or '대시보드에 별도 기재 없음'))
    for key, label in [('issue', '현황·이슈'), ('next', '다음 액션'), ('decision', '의사결정 요청')]:
        if task.get(key):
            lines.append('• ' + label + ': ' + clean(task[key]))
    if task.get('dueNote'):
        lines.append('• 일정 참고: ' + clean(task['dueNote'], 250))
    if task.get('verification'):
        lines.append('• 확인 상태: ' + clean(task['verification'], 250))
    return '\n'.join(lines) + reference(task)


def render(snapshot, now, base):
    day = now.date()
    monday = day - dt.timedelta(days=day.weekday())
    tasks = select_tasks(snapshot, monday, day)
    done = [t for t in tasks if t.get('status') == '완료' and date(t.get('completedDate'))]
    open_tasks = [t for t in tasks if t.get('status') != '완료']
    blockers = [t for t in open_tasks if t.get('status') in BLOCKED or t.get('decision')]
    next_monday = monday + dt.timedelta(days=7)
    next_friday = next_monday + dt.timedelta(days=4)
    plans = [t for t in open_tasks if t.get('next') and
             (not date(t.get('due')) or date(t['due']) <= next_friday)]
    meta = snapshot.get('meta', {})
    source = meta.get('daily', {}).get('sourceCutoff') or meta.get('sourceCutoffIso') or meta.get('sourceCutoff')
    if not source:
        raise Stop('Workboard source cutoff is missing.')
    # A stale board is never silently described as this week's report.
    source_day = date(str(source)[:10])
    if source_day is None or source_day < monday or source_day > day:
        raise Stop('Workboard source cutoff is outside the current report week.')
    intro = ['*[디자인팀 주간보고] 금주 주요 업무 진행현황 | ' + monday.strftime('%m/%d') + '~' + day.strftime('%m/%d') + '*',
             '조회: ' + now.strftime('%Y.%m.%d %H:%M') + ' KST ｜ 자동 취합 근거 마감: ' + clean(source),
             '대시보드 저장 상태 기준입니다. 조회 시점까지 저장된 수동 수정을 포함하며, 금주 진척을 별도로 추정하지 않습니다.',
             '*① 금주 핵심 요약*',
             '• 금주 완료 확인 ' + str(len(done)) + '건 ｜ 미완료 ' + str(len(open_tasks)) + '건 ｜ 미결·확인 필요 ' + str(len(blockers)) + '건']
    if done:
        intro.append('• 주요 완료: ' + ' / '.join(clean(t['title'], 100) for t in done[:3]))
    for task in open_tasks[:3]:
        intro.append('• 주요 진행: *' + clean(task['title'], 100) + '* ['
                     + clean(task.get('status') or '확인 필요') + '] — '
                     + clean(task.get('issue') or task.get('next') or '상세 현황 확인 필요', 180))
    intro += ['', '*③ 미결 이슈·의사결정 요청*']
    for task in blockers[:5]:
        intro.append('• *' + clean(task['title'], 100) + '* [' + clean(task.get('status')) + '] — '
                     + clean(task.get('decision') or task.get('issue') or '사유·일정 영향 확인 필요', 220))
    if not blockers:
        intro.append('• 등록된 미결 이슈 없음')
    elif len(blockers) > 5:
        intro.append('• 그 외 ' + str(len(blockers) - 5) + '건은 상세 스레드 참조')
    intro += ['', '*④ 차주 주요 계획 | ' + next_monday.strftime('%m/%d') + '~' + next_friday.strftime('%m/%d') + '*',
              '대시보드에 등록된 후속 액션입니다. 실행 주차 미확정 항목은 차주 확정 계획으로 간주하지 않습니다.']
    for task in plans[:5]:
        due = date(task.get('due'))
        timing = ('마감 ' + due.isoformat()) if due and next_monday <= due <= next_friday else '차주 실행 여부 확인 필요'
        intro.append('• *' + clean(task['title'], 100) + '* — ' + clean(task['next'], 180)
                     + ' ｜ ' + clean(task.get('owner') or '확인 필요', 80) + ' ｜ ' + timing)
    if not plans:
        intro.append('• 등록된 차주 후속 액션 없음')
    elif len(plans) > 5:
        intro.append('• 그 외 후속 액션은 상세 스레드 참조')
    intro += ['', '<' + base + '|디자인팀 업무 대시보드> · ② 프로젝트별 상세는 스레드 참조']
    # Split at task boundaries, retaining every selected task and its source link.
    parts, current = [], '*② 프로젝트별 진행현황*'
    for task in tasks:
        entry = card(task)
        if len(current) + len(entry) + 2 > 9500:
            parts.append(current)
            current = '*② 프로젝트별 진행현황 (계속)*'
        current += '\n\n' + entry
    parts.append(current if tasks else current + '\n등록된 업무 없음')
    if len('\n'.join(intro)) > 12000 or any(len(p) > 12000 for p in parts):
        raise Stop('Report exceeds safe message length.')
    return '\n'.join(intro), parts


def send_report(intro, parts, day):
    history = weekly.pages('conversations.history', {'channel': weekly.CHANNEL, 'oldest': str(
        dt.datetime.combine(day, dt.time(), KST).timestamp()), 'include_all_metadata': 'true'})
    roots = weekly.find_roots(history, day)
    key = day.isoformat()
    # Preserve legacy report deduplication during migration.
    if roots and roots[0].get('metadata', {}).get('event_type') != MARKER:
        print('An existing legacy report is present. No duplicate sent.')
        return
    digest = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()
    parent = roots[0] if roots else None
    if parent:
        if parent.get('user') != weekly.BOT:
            raise Stop('Existing report belongs to another author.')
        payload = parent.get('metadata', {}).get('event_payload', {})
        replies = weekly.thread(parent['ts'], str(time.time()))
        delivered = [m for m in replies[1:] if m.get('user') == weekly.BOT and
                     m.get('metadata', {}).get('event_type') == MARKER]
        if len(delivered) == payload.get('part_count'):
            print('Dashboard report already complete. No duplicate sent.')
            return
        if payload.get('digest') != digest:
            raise Stop('Partial report snapshot changed; review before retrying.')
    else:
        parent = weekly.slack('chat.postMessage', {'channel': weekly.CHANNEL,
            'text': intro + ('\n\n' + weekly.GROUP if weekly.GROUP else ''),
            'unfurl_links': False, 'unfurl_media': False,
            'metadata': {'event_type': MARKER, 'event_payload': {'report_key': key, 'digest': digest, 'part_count': len(parts)}}}, write=True)
        delivered = []
    delivered.sort(key=lambda m: float(m['ts']))
    for n, message in enumerate(delivered):
        if n >= len(parts) or message.get('text') != parts[n]:
            raise Stop('Existing report detail differs; no overwrite attempted.')
    for n in range(len(delivered), len(parts)):
        weekly.slack('chat.postMessage', {'channel': weekly.CHANNEL, 'thread_ts': parent['ts'], 'text': parts[n],
            'unfurl_links': False, 'unfurl_media': False, 'reply_broadcast': False,
            'metadata': {'event_type': MARKER, 'event_payload': {'report_key': key, 'part': n + 1}}}, write=True)
    replies = weekly.thread(parent['ts'], str(time.time()))
    actual = sorted([m for m in replies[1:] if m.get('user') == weekly.BOT and
                     m.get('metadata', {}).get('event_type') == MARKER], key=lambda m: float(m['ts']))
    if [m.get('text') for m in actual] != parts:
        raise Stop('Dashboard report readback differs.')
    print('PASS: Dashboard report and all detail replies verified.')


def main():
    now = dt.datetime.now(KST)
    publish = (os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and
               os.environ.get('FRIDAY_REPORTS_ENABLED') == 'true' and os.environ.get('PUBLISH') == 'true')
    if publish:
        weekly.wait_for_nominal(now, os.environ.get('REPORT_SCHEDULE', ''))
        now = dt.datetime.now(KST)
        if now.weekday() != 4 or not dt.time(17) <= now.time() < dt.time(19):
            raise Stop('Friday posting window is closed.')
    local = os.environ.get('DASHBOARD_SNAPSHOT_FILE')
    if local:
        if publish:
            raise Stop('Local snapshots cannot be published by the scheduler.')
        snapshot = json.loads(Path(local).read_text())
    else:
        snapshot = BoardAPI(os.environ.get('WORKBOARD_URL', ''), publish=False).call('snapshot')
    base = os.environ.get('WORKBOARD_URL', '').rstrip('/')
    if not re.fullmatch(r'https://[A-Za-z0-9.-]+', base):
        raise Stop('Workboard URL is invalid.')
    intro, parts = render(snapshot, now, base)
    if not publish:
        output = os.environ.get('DASHBOARD_PREVIEW_FILE')
        if output:
            Path(output).write_text(intro + '\n\n' + '\n\n'.join(parts))
        print('PASS: Dashboard draft validated. No Slack message sent. Detail parts: ' + str(len(parts)))
        return
    auth = weekly.slack('auth.test')
    if not weekly.CHANNEL or not weekly.BOT or not weekly.TEAM or auth.get('user_id') != weekly.BOT or auth.get('team_id') != weekly.TEAM:
        raise Stop('Unexpected Slack destination or identity.')
    send_report(intro, parts, now.date())


if __name__ == '__main__':
    try:
        main()
    except Stop as error:
        print('STOP: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('STOP: Dashboard report failed; no source data logged.', file=sys.stderr)
        sys.exit(1)
