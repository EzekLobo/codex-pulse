import unittest
from datetime import datetime, timedelta, timezone
from overlay import summarize, abbreviate, money, project_name

class OverlaySummaryTests(unittest.TestCase):
    def test_today_and_unknown_price_not_treated_as_known(self):
        now = datetime.now().astimezone()
        yesterday = now-timedelta(days=1)
        d={'calls':[{'id':'a','timestamp':now.isoformat(),'total':1500,'input':1200,'cached':900,'cost':.013,
                     'model':'x','prompt_id':'a'},
                    {'id':'b','timestamp':now.isoformat(),'total':500,'input':400,'cached':100,'cost':None},
                    {'id':'old','timestamp':yesterday.isoformat(),'total':90000,'input':90000,'cached':0,'cost':100}],
           'prompts':[{'id':'a','calls':2,'total':2000}], 'demo':False}
        m=summarize(d,now=now)
        self.assertEqual(m['today_calls'],2)
        self.assertEqual(m['tokens'],2000)
        self.assertAlmostEqual(m['cost'],.013)
        self.assertEqual(m['unknown_costs'],1)
        self.assertAlmostEqual(m['cache_percent'],1000/1600*100)
        self.assertEqual(m['prompt']['id'],'a')

    def test_no_calls_and_helpers(self):
        m=summarize({'calls':[]})
        self.assertEqual(m['cost'],0)
        self.assertIsNone(m['latest'])
        self.assertEqual(abbreviate(12100),'12,1k')
        self.assertEqual(money(None),'Sem tarifa')
        self.assertEqual(project_name('C:\\repo\\api'),'api')

if __name__=='__main__': unittest.main()
