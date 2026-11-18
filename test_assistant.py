import tempfile
import unittest
from unittest.mock import patch
import assistant as a
from knowledge import Knowledge
from test_learning import page

class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=a.STORE;a.STORE=Knowledge(self.tmp.name)
    def tearDown(self):a.STORE=self.old;self.tmp.cleanup()
    def test_live_knowledge_is_distinct_from_weights(self):
        with patch.object(a,'research',return_value=[page()]),patch.object(a,'model_reply',return_value='Plants produce oxygen. [1]'):
            r=a.chat(dict(message='What is photosynthesis?',web=True,learn=True))
        self.assertEqual(r['learned_pages'],1);self.assertFalse(r['weights_changed'])
        self.assertEqual(r['sources'][0]['revision_url'],page()['revision_url'])
    def test_drafting_does_not_search_or_store_private_prompt(self):
        with patch.object(a,'research') as research,patch.object(a,'model_reply',return_value='A short email.'):
            a.chat(dict(message='Help me write a polite email.',web=True,learn=True))
            research.assert_not_called()
        self.assertEqual(a.STORE.status()['knowledge_pages'],0)
    def test_unrelated_sources_and_fabricated_citations_are_not_used(self):
        a.STORE.remember([page()])
        with patch.object(a,'model_reply',return_value='Paris. [9]'):
            r=a.chat(dict(message='What is the capital of France?',web=False))
        self.assertEqual(r['sources'],[]);self.assertNotIn('[9]',r['answer'])
    def test_source_failure_is_reported(self):
        with patch.object(a,'research',side_effect=OSError('Offline')),patch.object(a,'model_reply',return_value='I do not know.'):
            r=a.chat(dict(message='Explain a new topic.',web=True))
        self.assertIn('Offline',r['warning'])
    def test_coding_requests_do_not_get_unrelated_article_evidence(self):
        with patch.object(a,'research') as search,patch.object(a.STORE,'recall') as recall,patch.object(a,'model_reply',return_value='print("hello")'):
            result=a.chat(dict(message='CODE A SIMPLE THING',web=True))
            search.assert_not_called();recall.assert_not_called();self.assertEqual(result['sources'],[])
    def test_bounded_calculation_avoids_network_and_model(self):
        with patch.object(a,'research') as research,patch.object(a,'model_reply') as model:
            r=a.chat(dict(message='What is 17 multiplied by 19?',web=True))
            self.assertEqual(r['answer'],'323');research.assert_not_called();model.assert_not_called()
        for text in ['__import__("os")','2**10000000','1/0']:
            self.assertIsNone(a.calculate(text))
    def test_code_reasoning_does_not_send_code_to_search(self):
        with patch.object(a,'research') as research,patch.object(a,'model_reply',return_value='[1, 2, 3]'):
            a.chat(dict(message='In Python, x=[1,2]; y=x; y.append(3). What is x?',web=True))
            research.assert_not_called()

if __name__=='__main__':unittest.main()
