"""Reconcile explicit leave notices without AI, messages, or report changes."""
import datetime as dt
import os
import re
import sys
import board_weekly as board

NOTICE = re.compile(r':(?:palm_tree|exclamation): \[([^\]]+)\] - .+ 휴가(?:입니다\.|가 취소되었습니다\.)')


def collect(user, cfg, now):
    identity = user.call('auth.test')
    if identity.get('team_id') != cfg['team_id'] or identity.get('bot_id'):
        raise board.Stop('Unexpected leave source identity.')
    channel_name = os.environ.get('SLACK_LEAVE_CHANNEL_NAME', '03_leave')
    channels = user.pages('conversations.list', {'types': 'public_channel', 'exclude_archived': 'true', 'limit': 200}, 'channels', max_pages=100)
    matches = [c for c in channels if c.get('name') == channel_name and not c.get('is_private') and not c.get('is_archived')]
    if len(matches) != 1:
        raise board.Stop('Expected public leave channel was not found.')
    channel = matches[0]['id']
    start = now - dt.timedelta(days=60)
    messages = user.pages('conversations.history', {'channel': channel, 'oldest': format(start.timestamp(), '.6f'), 'latest': format(now.timestamp(), '.6f'), 'inclusive': True, 'limit': 200}, max_pages=100)
    team = {person['name'] for person in cfg['designers']}
    rows = []
    for message in messages:
        if not message.get('bot_id'):
            continue
        if message.get('thread_ts') and message['thread_ts'] != message.get('ts'):
            continue
        text = message.get('text', '').strip()
        notice = NOTICE.fullmatch(text)
        if not notice or notice[1] not in team:
            continue
        if not re.fullmatch(r'\d{10}\.\d{6}', message.get('ts', '')):
            raise board.Stop('Invalid leave source timestamp.')
        rows.append({'ts': message['ts'], 'text': text, 'user': message.get('user', ''), 'bot_id': message.get('bot_id', ''),
                     'revision': message.get('edited', {}).get('ts') or message['ts']})
    if len(rows) > 2000:
        raise board.Stop('Leave reconciliation source limit reached.')
    return {'channelId': channel, 'complete': True, 'rows': rows, 'sourceStart': start.isoformat(), 'sourceCutoff': now.isoformat()}


def execute(now=None):
    if os.environ.get('GITHUB_EVENT_NAME') != 'schedule' or os.environ.get('BOARD_ENABLED') != 'true':
        raise board.Stop('Leave writes require the enabled scheduled workflow.')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if not re.fullmatch(r'\d+', run_id):
        raise board.Stop('Missing leave reconciliation run identity.')
    cfg = board.config_from_env()
    user = board.Slack(os.environ['SLACK_USER_TOKEN'], 'user')
    payload = collect(user, cfg, now or dt.datetime.now(board.KST))
    payload['runId'] = run_id
    api = board.BoardAPI(os.environ['WORKBOARD_URL'], publish=True)
    result = board.http_json(api.base + '/api/automation/leave-sync', api.token(), payload, 'Workboard')
    if not isinstance(result, dict) or result.get('error') or 'scanned' not in result:
        raise board.Stop('Leave reconciliation was not verified.')
    print('PASS: Scheduled leave reconciliation; scanned=' + str(result['scanned']) + '; changed=' + str(result.get('changed', 0)) + '; conflicts=' + str(result.get('conflicts', 0)), flush=True)


if __name__ == '__main__':
    try:
        execute()
    except board.Stop as error:
        print('STOP: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('STOP: Leave reconciliation failed; no private details logged.', file=sys.stderr)
        sys.exit(1)
