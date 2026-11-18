import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import coding_bench as bench
import coding_corpus as corpus
import community
import train_coding as training
import weight_jobs as jobs

class WeightTests(unittest.TestCase):
    def test_gates_reject_unchanged_overfit_and_coding_regression(self):
        before=dict(valid=2.,audit=2.);good=dict(valid=1.98,audit=1.99);score=dict(passes=7)
        self.assertTrue(training.policy(before,good,score,score,True)[0])
        for after,passes,changed in [(before,7,True),(dict(valid=1.98,audit=2.1),7,True),(good,6,True),(good,7,False)]:
            self.assertFalse(training.policy(before,after,score,dict(passes=passes),changed)[0])
    def test_split_stays_with_document_across_revisions(self):
        self.assertEqual(corpus.source_split('repo:path'),corpus.source_split('repo:path'))
        self.assertIn(corpus.source_split('repo:path'),{'train','valid','audit'})
    def test_failed_oversized_download_still_consumes_budget(self):
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        budget=dict(bytes=0,limit=10)
        with patch.object(corpus.urllib.request,'urlopen',return_value=Response(b'x'*20)):
            with self.assertRaises(ValueError):corpus.fetch('https://example.test',8,budget)
        self.assertEqual(budget['bytes'],8)
    def test_code_child_checks_correctness_and_mutation(self):
        self.assertEqual(bench.run_code('def dedupe(items):\n return list(dict.fromkeys(items))',bench.CASES[0]),[True]*3)
        for code in ['import os\ndef dedupe(x): return x','def dedupe(x): return open("private")','def dedupe(x): return x.__class__']:
            with self.assertRaises(ValueError):bench.validate(code,'dedupe')
    def test_pause_prevents_training_process(self):
        with patch('knowledge.Knowledge.state',return_value='false'),patch.object(jobs.subprocess,'Popen') as spawn:
            self.assertEqual(jobs.maybe_start()['phase'],'paused');spawn.assert_not_called()

class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.mock=patch.object(community,'ROOT',Path(self.tmp.name));self.mock.start()
        self.lesson=dict(title='Python function defaults',text='In Python, a function default is evaluated once when the function is defined. Use None and create a fresh list inside the function when a new mutable value is required.',attribution='Test contributor',license='MIT',original=True)
    def tearDown(self):self.mock.stop();self.tmp.cleanup()
    def test_no_consent_no_capture_and_never_whole_chats(self):
        self.assertIsNone(community.capture('Correction: '+self.lesson['text']))
        community.configure(True,'https://github.com/'+community.GITHUB_REPOSITORY)
        self.assertIsNone(community.capture('Please debug my private function.'))
        self.assertEqual(community.capture('Correction: '+self.lesson['text'])['state'],'queued')
        community.configure(False)
        self.assertEqual(community.deliver()['state'],'paused')
    def test_review_gate_dedup_and_sensitive_content(self):
        ident=community.store(self.lesson);self.assertEqual(ident,community.store(self.lesson));self.assertEqual(community.records(),[])
        community.review(ident,True,'Reviewed for Python correctness and original ownership')
        self.assertEqual(len(community.records()),1)
        community.review(ident,False,'Retracted');self.assertEqual(community.records(),[])
        for extra in [' api_key=longsecret123',' person@example.test',' /Users/private/project']:
            with self.assertRaises(ValueError):community.validate(dict(self.lesson,text=self.lesson['text']+extra))
        with self.assertRaises(ValueError):community.validate(dict(self.lesson,original=False))
    def test_attribution_or_title_changes_invalidate_approval_hash(self):
        original=community.validate(self.lesson)['id']
        self.assertNotEqual(original,community.validate(dict(self.lesson,title='Different coding title'))['id'])
    def test_auto_delivery_uses_only_queued_lesson_and_rechecks_pause(self):
        community.configure(True,'https://github.com/'+community.GITHUB_REPOSITORY)
        community.capture('Share lesson: '+self.lesson['text'])
        with patch.object(community,'github_submit',return_value='https://github.com/example/issue/1') as submit:
            self.assertEqual(community.deliver()['sent'],1)
            sent=submit.call_args.args[0];self.assertIn('function default',sent['text']);self.assertNotIn('history',sent)
            self.assertEqual(community.deliver()['sent'],0);self.assertEqual(submit.call_count,1)
    def test_github_approval_requires_owner_hash_not_just_label(self):
        import json
        item=community.validate(self.lesson)
        issue=dict(body='```json\n'+json.dumps(item)+'\n```',comments_url='https://example.test/comments',html_url='https://example.test/1')
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        def responses(comments):return [Response(json.dumps([issue]).encode()),Response(json.dumps(comments).encode())]
        with patch.object(community.urllib.request,'urlopen',side_effect=responses([])):
            self.assertEqual(community.sync_github()['approved'],0)
        comment=dict(user=dict(login='malkhalaf23'),body='Training-approved SHA256: '+item['id'])
        with patch.object(community.urllib.request,'urlopen',side_effect=responses([comment])):
            self.assertEqual(community.sync_github()['approved'],1)
        self.assertEqual(len(community.records()),1)

if __name__=='__main__':unittest.main()
