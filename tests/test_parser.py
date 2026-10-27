import json
import tempfile
import unittest
from pathlib import Path
from codex_pulse import aggregate, parse_rollout, tokens, estimated_cost

PRICE={'gpt-5.3-codex': {'input':1.75,'cached':.175,'output':14.0}}


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(x) for x in rows)+'\n',encoding='utf-8')


def rec(t,typ,p):
    return {'timestamp':f'2026-10-26T{t}Z','type':typ,'payload':p}


class ParserTests(unittest.TestCase):
    def test_modern_calls_dedupe_cache_cost_prompts(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root)
            lines=[
                rec('10:00:00','session_meta',{'id':'sid01','originator':'Codex Desktop','cwd':'/src/api'}),
                rec('10:00:01','event_msg',{'type':'user_message','message':'Crie testes da API'}),
                rec('10:00:02','turn_context',{'model':'gpt-5.3-codex','reasoning_effort':'high'}),
                rec('10:00:03','response_item',{'type':'function_call','name':'exec_command'}),
                rec('10:00:04','token_usage_record',{'response_id':'resp1','turn_id':'tid01','usage':{'input_tokens':1000,'cached_input_tokens':800,'output_tokens':200,'reasoning_output_tokens':100}}),
                rec('10:00:05','event_msg',{'type':'token_count','info':{'total_token_usage':{'input_tokens':1000,'cached_input_tokens':800,'output_tokens':200}}}),
                rec('10:00:06','token_usage_record',{'response_id':'resp2','turn_id':'tid01','usage':{'input_tokens':500,'cached_input_tokens':300,'output_tokens':100,'reasoning_output_tokens':50}}),
                rec('10:00:07','event_msg',{'type':'task_complete','turn_id':'tid01','duration_ms':12000}),
            ]
            write(home/'sessions'/'2026'/'10'/'26'/'rollout-modern.jsonl', lines)
            write(home/'archived_sessions'/'rollout-copied.jsonl', lines)
            data=aggregate(home,PRICE)
            self.assertEqual(len(data['calls']),2)
            self.assertEqual(sum(c['total'] for c in data['calls']),1800)
            self.assertEqual(sum(c['cached'] for c in data['calls']),1100)
            self.assertEqual(data['prompts'][0]['duration_ms'],12000)
            self.assertEqual(data['prompts'][0]['prompt'],'Crie testes da API')
            self.assertEqual(data['calls'][0]['effort'],'high')
            # (200+200)*1.75 + (800+300)*.175 + (200+100)*14 divided by 1M.
            self.assertAlmostEqual(sum(c['cost'] for c in data['calls']), (400*1.75+1100*.175+300*14)/1e6)

    def test_legacy_cumulative_repeated_and_rate_limit(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root)
            lines=[rec('10:00:00','session_meta',{'id':'s2','cwd':'/old'}),rec('10:00:01','turn_context',{'model':'gpt-5.3-codex'})]
            def event(t, inp, cached, output):
                return rec(t,'event_msg',{'type':'token_count','info':{'total_token_usage':{'input_tokens':inp,'cached_input_tokens':cached,'output_tokens':output}},'rate_limits':{'primary':{'window_minutes':300,'used_percent':20,'resets_at':1800000000}}})
            lines += [event('10:00:02',1000,400,100),event('10:00:03',1000,400,100),event('10:00:04',2200,1400,130)]
            write(home/'sessions'/'rollout-old.jsonl',lines)
            data=aggregate(home,PRICE)
            self.assertEqual(len(data['calls']),2)
            self.assertEqual(sum(x['input'] for x in data['calls']),2200)
            self.assertEqual(sum(x['output'] for x in data['calls']),130)
            self.assertEqual(data['limits']['primary']['used_percent'],20)

    def test_malformed_lines_and_unknown_prices(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'rollout-damaged.jsonl'
            path.write_text('{broken\n'+json.dumps(rec('12:00:00','turn_context',{'model':'unknown-model'}))+'\n'+json.dumps(rec('12:00:01','token_usage_record',{'response_id':'resp3','usage':{'input_tokens':200,'cached_input_tokens':350,'output_tokens':10,'reasoning_output_tokens':12}}))+'\n',encoding='utf8')
            result=parse_rollout(path)
            self.assertEqual(result['responses'][0]['usage']['cached_input_tokens'],200)
            self.assertEqual(result['responses'][0]['usage']['reasoning_output_tokens'],10)
            self.assertIsNone(estimated_cost(result['responses'][0]['usage'],'unknown-model',PRICE))
            self.assertEqual(tokens({'input_tokens':10,'cached_input_tokens':20})['total_tokens'],10)


if __name__=='__main__':unittest.main()
