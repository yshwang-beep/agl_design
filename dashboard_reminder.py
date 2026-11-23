"""Monday 09:05 KST dashboard check reminder, independent of collection."""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KST = dt.timezone(dt.timedelta(hours=9))
CHANNEL = 'C03HP4CBHAQ'
GROUP = '<!subteam^S09FW5GBM7G>'
URL = 'https://agl-design-workboard.agl-design-workboard-cloud.workers.dev'
TITLE = '[디자인팀 주간 업무 보고] 담당별 업무 현황 확인 요청'


def notice_text(today):
    monday = today - dt.timedelta(days=today.weekday())
    start, end = monday - dt.timedelta(days=7), monday - dt.timedelta(days=1)
    label = start.strftime('%Y.%m.%d') + '(월) – ' + end.strftime('%m.%d') + '(일)'
    return ('*' + TITLE + '* ' + GROUP
            + '\n\n주간 업무 보고를 위해 *담당별 업무 현황 대시보드가 업데이트되었습니다.*'
            + '\n\n주간 미팅 전, 담당 업무의 진행 현황과 보고 내용에 누락이나 오류가 없는지 확인하고 필요한 사항을 수정해 주세요.'
            + '\n\n1. *보고 기간:* ' + label
            + '\n2. *수정 기한:* 금일 10:00 전까지'
            + '\n3. *주요 점검 항목*'
            + '\n\n• 업무별 진행 상태 및 진척도'
            + '\n• 주요 이슈 및 특이사항'
            + '\n• 다음 액션(Next Action)'
            + '\n• 의사결정 및 협의 요청 사항'
            + '\n\n🔗 <' + URL + '|담당별 업무 현황 대시보드 바로가기>')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api(method, params=None, write=False):
    endpoint = 'https://slack.com/api/' + method
    payload = json.dumps(params or {}).encode() if write else None
    if not write:
        endpoint += '?' + urllib.parse.urlencode(params or {})
    request = urllib.request.Request(endpoint, data=payload, headers={
        'Authorization': 'Bearer ' + os.environ['SLACK_BOT_TOKEN'],
        'Content-Type': 'application/json; charset=utf-8'})
    # Never automatically retry a write with an uncertain outcome.
    for attempt in range(4):
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
                result = json.load(response)
            if not result.get('ok'):
                raise RuntimeError('Slack operation rejected: ' + (result.get('error') if result.get('error') in {'missing_scope','not_in_channel','channel_not_found','invalid_auth','token_revoked','account_inactive','ratelimited','restricted_action'} else 'request_rejected'))
            return result
        except urllib.error.HTTPError as error:
            if not write and error.code == 429 and attempt < 3:
                delay = int(error.headers.get('Retry-After', '30'))
                if 0 <= delay <= 60:
                    time.sleep(delay + 1)
                    continue
            raise RuntimeError('Slack HTTP request failed; verify delivery before retrying.') from None


def run(now=None):
    now = now or dt.datetime.now(KST)
    cfg = json.loads(os.environ['BOARD_CONFIG'])
    identity = api('auth.test')
    if identity.get('team_id') != cfg['team_id'] or identity.get('user_id') != cfg['bot_user_id']:
        raise RuntimeError('Unexpected bot identity.')
    if CHANNEL not in cfg['core_channel_ids']:
        raise RuntimeError('Unexpected reminder destination.')
    # Use the existing bot channel-history scope; no new channel-info permission.
    api('conversations.history', {'channel': CHANNEL, 'limit': 1})
    if os.environ.get('GITHUB_EVENT_NAME') != 'schedule':
        print('PASS: Reminder preflight verified; no Slack message sent.')
        return
    if now.weekday() != 0 or not dt.time(9, 5) <= now.time() < dt.time(10):
        raise RuntimeError('Reminder delivery is limited to Monday 09:05–10:00 KST.')
    text = notice_text(now.date())
    oldest = str(dt.datetime.combine(now.date(), dt.time(), KST).timestamp())
    cursor = None
    for _ in range(100):
        page = api('conversations.history', {'channel': CHANNEL, 'oldest': oldest, 'limit': 100, **({'cursor': cursor} if cursor else {})})
        if any(m.get('text') == text for m in page.get('messages', [])):
            print('PASS: Existing exact reminder reused; no duplicate sent.')
            return
        cursor = page.get('response_metadata', {}).get('next_cursor')
        if not cursor:
            break
    else:
        raise RuntimeError('Could not completely verify reminder history.')
    # Recheck the deadline after reads, immediately before the only write.
    current = dt.datetime.now(KST)
    if current.date() != now.date() or current.time() >= dt.time(10):
        raise RuntimeError('Reminder deadline passed before sending.')
    sent = api('chat.postMessage', {'channel': CHANNEL, 'text': text, 'unfurl_links': False, 'unfurl_media': False}, write=True)
    if sent.get('channel') != CHANNEL or not sent.get('ts'):
        raise RuntimeError('Reminder outcome uncertain; verify before retrying.')
    verified = api('conversations.history', {'channel': CHANNEL, 'oldest': sent['ts'], 'latest': sent['ts'], 'inclusive': 'true', 'limit': 1})
    if not any(m.get('ts') == sent['ts'] and m.get('text') == text for m in verified.get('messages', [])):
        raise RuntimeError('Reminder readback failed; verify before retrying.')
    print('PASS: Monday dashboard reminder delivered and read back.')


def self_test():
    from unittest.mock import patch
    text = notice_text(dt.date(2026, 11, 23))
    assert '2026.11.16(월) – 11.22(일)' in text
    assert GROUP in text and '<@' not in text and '(cc.' not in text
    assert all(s in text for s in ['1. *보고 기간:*', '2. *수정 기한:*', '3. *주요 점검 항목*', '다음 액션(Next Action)'])
    assert '2025.12.29(월) – 01.04(일)' in notice_text(dt.date(2026, 1, 5))
    cfg = {'team_id': 'TEST', 'bot_user_id': 'BOT', 'core_channel_ids': [CHANNEL]}
    replies = [{'team_id': 'TEST', 'user_id': 'BOT'}, {'channel': {'is_channel': True}}]
    with patch.dict(os.environ, {'BOARD_CONFIG': json.dumps(cfg), 'GITHUB_EVENT_NAME': 'workflow_dispatch'}), patch(__name__ + '.api', side_effect=replies) as client:
        run(dt.datetime(2026, 11, 23, 9, 5, tzinfo=KST))
        assert client.call_count == 2 and not any(c.kwargs.get('write') for c in client.call_args_list)
    print('PASS: Reminder dates, exact format, group-only mention and read-only manual preflight.')


if __name__ == '__main__':
    try:
        self_test() if '--self-test' in sys.argv else run()
    except Exception as error:
        message = str(error) if isinstance(error, RuntimeError) else 'Dashboard reminder failed; no private details logged.'
        print('STOP: ' + message + ' Verify delivery before retrying.', file=sys.stderr)
        sys.exit(1)
