import datetime as dt
import unittest
from unittest.mock import patch
import design_briefing as b
import prepare_briefing as p
class PreparationTests(unittest.TestCase):
    def test_weekday_targets_and_late_catchup(self):
        for now,expected in [('2026-11-19T12:00:00+09:00','2026-11-20'),('2026-11-20T09:10:00+09:00','2026-11-20'),('2026-11-20T10:05:00+09:00','2026-11-23'),('2026-11-22T20:00:00+09:00','2026-11-23')]:
            self.assertEqual(p.targets(dt.datetime.fromisoformat(now))[0].isoformat(),expected)
    def test_friday_fallback_to_verified_inspiration(self):
        date=dt.date(2026,11,27)
        empty={'temporary_holiday':False,'items':[]}
        draft={'temporary_holiday':False,'items':[{'source_url':'https://example.com/a'}]}
        with patch.object(b,'research',return_value=('research',{'https://example.com/a'})) as research,patch.object(b,'structure',side_effect=[empty,empty,empty,draft]),patch.object(b,'verify_item',return_value={'source_url':'https://example.com/a'}):
            kind,items=p.verified_items(date,'events',[],set())
            self.assertEqual(kind,'inspiration')
            self.assertEqual(research.call_args_list[-1].args[1],'inspiration')
    def test_fixed_topics_and_holidays(self):
        h=b.holiday_calendar(2026)
        for day,kind in [(16,'tools'),(17,None),(18,'practice'),(19,None),(20,'events'),(21,None),(22,None)]:
            self.assertEqual(b.category_for(dt.date(2026,11,day),h),kind)
        self.assertIsNone(b.category_for(dt.date(2026,12,25),h))
    def test_ungrounded_claims_are_rebuilt_from_original(self):
        item={'source_url':'https://example.com/a','source_date':'2026-11-19'}
        rebuilt={**item,'title':'Rebuilt from original'}
        with patch.object(b,'verify_item',side_effect=[b.Stop('Original source evidence could not be confirmed.'),rebuilt]) as verify,patch.object(b,'public_read',return_value=(b'<p>Actual original evidence</p>','text/html',item['source_url'])),patch.object(b,'structure',return_value={'temporary_holiday':False,'items':[rebuilt]}) as structure:
            result=p.verify_candidate(item,dt.date(2026,11,20),'events',{item['source_url']},set())
            self.assertEqual(result,rebuilt)
            self.assertIn('Actual original evidence',structure.call_args.args[0])
            self.assertEqual(verify.call_args.args[0],rebuilt)
    def test_rebuilt_candidate_cannot_change_source(self):
        item={'source_url':'https://example.com/a','source_date':'2026-11-19'}
        with patch.object(b,'verify_item',side_effect=b.Stop('Original source evidence could not be confirmed.')),patch.object(b,'public_read',return_value=(b'<p>Original</p>','text/html',item['source_url'])),patch.object(b,'structure',return_value={'temporary_holiday':False,'items':[{**item,'source_url':'https://example.com/b'}]}):
            with self.assertRaises(b.Stop): p.verify_candidate(item,dt.date(2026,11,20),'events',{item['source_url']},set())
if __name__=='__main__': unittest.main()
