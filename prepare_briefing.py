"""Prepare verified M/W/F issues ahead of delivery; never print drafts or tokens."""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import design_briefing as b

BASE = 'https://agl-design-briefing.agl-design-workboard-cloud.workers.dev'

def queue_api(path, payload):
    audience = BASE + '/automation'
    token_url = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'] + '&audience=' + urllib.parse.quote(audience, safe='')
    req = urllib.request.Request(token_url, headers={'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    with urllib.request.urlopen(req, timeout=30) as res:
        token = json.load(res)['value']
    req = urllib.request.Request(BASE + path, data=json.dumps(payload, ensure_ascii=False).encode(),
                                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.load(res)

def targets(now):
    """Prepare at most the next issue, up to 72h ahead. Do not shift holiday posts."""
    for offset in range(4):
        day=now.date()+dt.timedelta(days=offset)
        due=dt.datetime.combine(day,dt.time(9,5),b.KST)
        if day.weekday() in (0,2,4) and now < due+dt.timedelta(hours=1) and due <= now+dt.timedelta(hours=72):
            return [day]
    return []

def verified_items(day, category, prior, excluded):
    region='international' if next((p for p in prior if p.get('category')!='events'),{}).get('region')=='domestic' else 'domestic'
    blocked={'helpx.adobe.com'}
    # Friday fallback gets independent research and the ordinary-article checks.
    categories=[category,'inspiration'] if category=='events' else [category]
    for kind in categories:
        for attempt in range(3):
            report, allowed=b.research(day,kind,region if attempt%2==0 else ('domestic' if region=='international' else 'international'),excluded,blocked)
            draft=b.structure(report,kind,day)
            if draft['temporary_holiday']:
                url=b.canonical(draft['holiday_source'])
                if url not in allowed or not urllib.parse.urlsplit(url).hostname.endswith('.go.kr'):
                    raise b.Stop('Unverified temporary holiday.')
                return None,None
            try:
                items=draft['items']
                if not (1<=len(items)<=3 if kind=='events' else len(items)==1):
                    raise b.Stop('No suitable verified content.')
                checked=[b.verify_item(item,day,kind,allowed,excluded) for item in items]
                if len({i['source_url'] for i in checked})!=len(checked):
                    raise b.Stop('Duplicate event sources.')
                return kind,checked
            except (b.Stop,ValueError):
                print('Candidate validation failed; trying another original source.')
                for item in draft['items']:
                    try: excluded.add(b.canonical(item['source_url']))
                    except (b.Stop,ValueError,KeyError): pass
    raise b.Stop('No verified issue after bounded research; preparation can be retried.')

def verify_test(day):
    for _ in range(20):
        status=queue_api('/status', {'date':day.isoformat(),'test':True})
        print('Delivery verification:', json.dumps(status), flush=True)
        if status['status']=='delivered': return
        if status['status'] in ('expired','content_mismatch'): raise b.Stop('Test delivery failed.')
        time.sleep(30)
    raise b.Stop('Test delivery verification timed out.')

def main():
    now=dt.datetime.now(b.KST)
    test=os.environ.get('BRIEFING_TEST')=='true'
    days=[now.date()] if test else targets(now)
    for day in days:
        status=queue_api('/status',{'date':day.isoformat(),'test':test})
        if status['status'] in ('queued','delivered','skipped','sending','uncertain','retry','content_mismatch','expired'):
            print('Existing issue:',day.isoformat(),json.dumps(status),flush=True)
            if test: verify_test(day)
            continue
        calendar=b.holiday_calendar(day.year,json.loads(os.environ.get('BRIEFING_EXTRA_HOLIDAYS','[]')))
        category='practice' if test else b.category_for(day,calendar)
        if not category:
            result=queue_api('/queue',{'date':day.isoformat(),'skip':True})
            print('Holiday skipped:',day.isoformat(),result['status'])
            continue
        channel=os.environ['BRIEFING_CHANNEL_ID']
        auth=b.slack('auth.test',{})
        if auth.get('team_id')!=os.environ['SLACK_TEAM_ID'] or auth.get('user_id')!=os.environ['SLACK_BOT_USER_ID']:
            raise b.Stop('Slack identity mismatch.')
        rows=b.history(channel,now)
        prior=b.receipts(rows,auth['user_id'])
        excluded={b.canonical(u) for p in prior for u in p.get('source_urls',[])}
        excluded.update(b.previous_editorial_urls(rows))
        excluded.update(b.canonical(u) for u in json.loads(os.environ.get('BRIEFING_EXCLUDED_URLS','[]')))
        kind,items=verified_items(day,category,prior,excluded)
        if not items:
            if test: raise b.Stop('Test cannot publish on confirmed temporary holiday.')
            queue_api('/queue',{'date':day.isoformat(),'skip':True})
            print('Verified temporary holiday skipped.')
            continue
        blocks=b.blocks_for(items,kind,os.environ['BRIEFING_GROUP_MENTION'],day)
        message={'channel':channel,'text':b.SHORT_TITLES[kind]+' '+items[0]['title'],'blocks':blocks,
                 'metadata':{'event_type':b.EVENT_TYPE,'event_payload':{
                     'date':day.isoformat(),'category':kind,'region':items[0]['region'],
                     'source_urls':[i['source_url'] for i in items], 'test':test}}}
        result=queue_api('/queue',{'date':day.isoformat(),'test':test,'token':os.environ['SLACK_BOT_TOKEN'],'message':message})
        print('Verified issue queued:',day.isoformat(),json.dumps(result),flush=True)
        if test: verify_test(day)

if __name__=='__main__':
    try: main()
    except Exception as e:
        # urllib exceptions can contain credential-bearing request details. Only type is public.
        print('Preparation failed:',type(e).__name__,file=sys.stderr)
        raise SystemExit(1)
