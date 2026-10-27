import unittest
from datetime import datetime, timedelta, timezone
from overlay import quota_info, summarize, timeline, prices_from_file, money

UTC = timezone.utc
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def make_call(delta_minutes, session='a', cost=.002, count=500):
    return {'timestamp': (NOW + timedelta(minutes=delta_minutes)).isoformat(),
            'session_id': session, 'input': count-100, 'cached': 200,
            'total': count, 'cost': cost, 'prompt_id': 'prompt-a'}


class OverlayV3Tests(unittest.TestCase):
    def test_filters_today_hour_latest_session(self):
        data={'calls':[make_call(-5,'a'), make_call(-120,'b',cost=None),make_call(-1500,'a')],
              'prompts':[{'id':'prompt-a','prompt':'corrija a API'}]}
        daily=summarize(data, NOW, 'today')
        last_hour=summarize(data, NOW, 'hour')
        session=summarize(data, NOW, 'session')
        self.assertEqual(daily['calls'],2)
        self.assertEqual(daily['unknown_costs'],1)
        self.assertEqual(daily['tokens'],1000)
        self.assertEqual(last_hour['calls'],1)
        self.assertEqual(session['calls'],2)
        self.assertEqual(daily['prompt']['prompt'],'corrija a API')

    def test_stale_quota_not_confused_with_live(self):
        limits={'timestamp':(NOW-timedelta(hours=1)).isoformat(),
                'primary':{'used_percent':95,'window_minutes':300,'resets_at':(NOW+timedelta(hours=3)).timestamp()}}
        q=quota_info(limits,NOW)
        self.assertTrue(q['stale'])
        self.assertFalse(q['expired'])
        self.assertEqual(q['percent'],95)

    def test_expired_quota_marked_unknown(self):
        limits={'timestamp':(NOW-timedelta(hours=6)).isoformat(),
                'primary':{'used_percent':80,'window_minutes':300,'resets_at':(NOW-timedelta(hours=1)).timestamp()}}
        q=quota_info(limits,NOW)
        self.assertTrue(q['expired'])
        self.assertIsNone(q['percent'])

    def test_quota_relative_reset_and_zero_count(self):
        limits={'timestamp':(NOW-timedelta(hours=1)).isoformat(),
                'primary':{'used_percent':50,'window_minutes':300,'resets_in_seconds':120}}
        self.assertTrue(quota_info(limits,NOW)['expired'])
        self.assertIsNone(quota_info(None,NOW)['percent'])

    def test_timeline_and_future_ignored(self):
        calls=[make_call(-20,count=500),make_call(-5,count=200),make_call(8,count=9000)]
        line=timeline(calls,NOW,'hour',bins=12)
        self.assertEqual(sum(line),700)
        self.assertEqual(len(line),12)

    def test_partial_price_and_currency(self):
        data={'calls':[make_call(-1,cost=None),make_call(-2,cost=.02345)]}
        r=summarize(data,NOW,'today')
        self.assertEqual(r['unknown_costs'],1)
        self.assertEqual(money(r['cost'],True),'US$ 0,0234*')
        self.assertGreater(len(prices_from_file()),0)

if __name__=='__main__': unittest.main()
