import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.parse
import knowledge as k

def page(title='Photosynthesis',language='en'):
    return dict(title=title,text=('Photosynthesis uses sunlight, water and carbon dioxide to produce sugars and oxygen. '*8),
        url=f'https://{language}.wikipedia.org/wiki/'+urllib.parse.quote(title.replace(' ','_')),
        language=language,license='CC-BY-SA-4.0',revision='123',
        revision_url=f'https://{language}.wikipedia.org/w/index.php?oldid=123',links=[])

def reader(**kwargs):return [page(kwargs['title'],kwargs['language'])],1000

class LearningTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=k.Knowledge(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_provenance_and_permission(self):
        bad=dict(page(),url='https://example.com/article')
        unknown=dict(page(),license='unknown')
        self.assertEqual(self.store.remember([bad,unknown]),0)
        self.assertEqual(self.store.remember([page()]),1)
        self.assertEqual(self.store.remember([page()]),0)
        rows=self.store.recall('How does photosynthesis use sunlight?')
        self.assertEqual(rows[0]['revision'],'123');self.assertEqual(len(rows[0]['sha']),64)
        self.assertEqual(self.store.recall('What is the capital of France?'),[])
    def test_pause_and_hourly_throttle(self):
        self.store.set_state('enabled','false')
        self.assertEqual(self.store.cycle(force=True,reader=reader)['state'],'paused')
        self.store.set_state('enabled','true')
        self.assertEqual(self.store.cycle(reader=reader)['added'],2)
        self.assertEqual(self.store.cycle(reader=reader)['state'],'waiting')
    def test_daily_bounds_and_reset(self):
        with patch.object(k,'daykey',return_value='2026-11-18'):
            for _ in range(10):self.store.cycle(force=True,reader=reader)
            s=self.store.status();self.assertEqual(s['pages_today'],12);self.assertLessEqual(s['bytes_today'],2_000_000)
            self.assertEqual(self.store.cycle(force=True,reader=reader)['attempted'],0)
        with patch.object(k,'daykey',return_value='2026-11-19'):
            # No more initial seeds? Add an explicit approved topic for the next day.
            with self.store.db() as db:db.execute('INSERT INTO frontier(language,title) VALUES (?,?)',('en','Physics'))
            self.assertGreater(self.store.cycle(force=True,reader=reader)['read'],0)
    def test_failed_downloads_are_charged_and_bounded(self):
        calls=[]
        def fail(**kwargs):calls.append(kwargs);raise OSError('network unavailable')
        for _ in range(10):self.store.cycle(force=True,reader=fail)
        self.assertLessEqual(len(calls),10)
        self.assertLessEqual(self.store.status()['bytes_today'],2_000_000)
        self.assertTrue(self.store.status()['events'])
    def test_concurrent_cycles_do_not_duplicate(self):
        started=threading.Event();release=threading.Event()
        def slow(**kwargs):started.set();release.wait(2);return reader(**kwargs)
        thread=threading.Thread(target=lambda:self.store.cycle(force=True,reader=slow));thread.start()
        self.assertTrue(started.wait(2))
        self.assertEqual(self.store.cycle(force=True,reader=reader)['state'],'busy')
        release.set();thread.join(3);self.assertFalse(thread.is_alive())
    def test_unchanged_weekly_refresh_updates_freshness(self):
        self.store.cycle(force=True,reader=reader)
        with self.store.db() as db:db.execute("UPDATE pages SET updated='2020-01-01T00:00:00+00:00'")
        result=self.store.cycle(force=True,reader=reader)
        self.assertEqual(result['added'],0)
        with self.store.db() as db:dates=[r['updated'] for r in db.execute('SELECT updated FROM pages')]
        self.assertTrue(all(not d.startswith('2020') for d in dates))
    def test_persists_across_restarts(self):
        self.store.remember([page()]);self.store.set_state('enabled','false')
        restarted=k.Knowledge(self.tmp.name)
        self.assertEqual(restarted.status()['knowledge_pages'],1);self.assertFalse(restarted.status()['enabled'])
    def test_public_https_boundary(self):
        for url in ['http://example.com','file:///etc/passwd','https://127.0.0.1/','https://user:password@example.com']:
            with self.assertRaises(ValueError):k.public_url(url)
    def test_parser_rejects_disambiguation_and_missing_revision(self):
        raw=dict(query=dict(pages={'1':dict(title='Ambiguous',extract='x'*300,pageprops={'disambiguation':''},revisions=[dict(revid=123)])}))
        self.assertEqual(k.parse_pages(raw,'en'),[])

if __name__=='__main__':unittest.main()
