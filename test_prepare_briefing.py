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
        date=dt.date(2026,11,20)
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
if __name__=='__main__': unittest.main()
