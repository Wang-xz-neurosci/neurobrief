import contextlib
import datetime as dt
from email.message import Message
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('api_updater',ROOT/'scripts/update_papers.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class ApiCourtesyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'.local').mkdir(exist_ok=True)

    def error(self,code,retry=None):
        headers=Message()
        if retry is not None:headers['Retry-After']=str(retry)
        return HTTPError('https://example.invalid',code,'test',headers,None)
    def response(self):return contextlib.nullcontext(io.BytesIO(b'{"hitCount":0,"resultList":{"result":[]}}'))
    def test_access_denial_does_not_trigger_repeated_requests(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder,patch.object(m,'ROOT',Path(folder)),patch.object(m,'_last_request_started',0),patch.object(m.time,'monotonic',return_value=100),patch.object(m.time,'sleep'):
            with patch.object(m,'urlopen',side_effect=self.error(403)) as request:
                with self.assertRaises(HTTPError):m.request_json({'query':'brain'})
                self.assertEqual(request.call_count,1)
            self.assertTrue((Path(folder)/'data/source_cooldown.json').exists())
    def test_short_retry_after_is_respected(self):
        with patch.object(m,'_last_request_started',0),patch.object(m.time,'monotonic',return_value=100),patch.object(m.time,'sleep') as sleep:
            with patch.object(m,'urlopen',side_effect=[self.error(429,7),self.response()]) as request:
                self.assertEqual(m.request_json({'query':'brain'})['hitCount'],0)
                self.assertEqual(request.call_count,2)
            sleep.assert_any_call(7)
    def test_long_retry_after_pauses_the_batch_and_records_cooldown(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder,patch.object(m,'ROOT',Path(folder)),patch.object(m,'_last_request_started',0),patch.object(m.time,'monotonic',return_value=100),patch.object(m.time,'sleep'):
            with patch.object(m,'urlopen',side_effect=self.error(429,120)) as request:
                with self.assertRaises(m.SourceDeferred):m.request_json({'query':'brain'})
                self.assertEqual(request.call_count,1)
            import json
            value=json.loads((Path(folder)/'data/source_cooldown.json').read_text())
            self.assertGreater(dt.datetime.fromisoformat(value['retry_after']),dt.datetime.now(dt.timezone.utc))
    def test_temporary_503_defers_after_finite_retries_and_keeps_saved_data(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder,patch.object(m,'ROOT',Path(folder)),patch.object(m,'_last_request_started',0),patch.object(m.time,'monotonic',return_value=100),patch.object(m.time,'sleep') as sleep:
            saved=Path(folder)/'data/candidates.json';saved.parent.mkdir();saved.write_text('last-success')
            with patch.object(m,'urlopen',side_effect=self.error(503)) as request:
                with self.assertRaises(m.SourceDeferred):m.request_json({'query':'brain'})
                self.assertEqual(request.call_count,4)
            self.assertEqual(saved.read_text(),'last-success')
            self.assertTrue((Path(folder)/'data/source_cooldown.json').exists())
            sleep.assert_any_call(60)
    def test_invalid_query_is_not_retried(self):
        with patch.object(m,'_last_request_started',0),patch.object(m.time,'monotonic',return_value=100),patch.object(m.time,'sleep'):
            with patch.object(m,'urlopen',side_effect=self.error(400)) as request:
                with self.assertRaises(HTTPError):m.request_json({'query':'bad'})
                self.assertEqual(request.call_count,1)
    def test_consecutive_requests_have_a_one_second_start_interval(self):
        with patch.object(m,'_last_request_started',0),patch.object(m.time,'monotonic',return_value=100),patch.object(m.time,'sleep') as sleep:
            with patch.object(m,'urlopen',side_effect=[self.response(),self.response()]):
                m.request_json({'query':'one'});m.request_json({'query':'two'})
            sleep.assert_any_call(1)


if __name__=='__main__':unittest.main()
