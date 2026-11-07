import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_papers as updater


def response(rows, count, cursor=None):
    return {'hitCount': count, 'resultList': {'result': rows}, 'nextCursorMark': cursor}


class PaginationTests(unittest.TestCase):
    def test_terminal_page_keeps_rows_despite_an_overreported_hit_count(self):
        rows = [{'source': 'MED', 'id': str(i)} for i in range(134)]
        with patch.object(updater, 'request_json', return_value=response(rows, 136)) as api:
            fetched, count = updater.fetch_pages('brain')
        self.assertEqual(fetched, rows)
        self.assertEqual(count, 136)
        api.assert_called_once()

    def test_follow_cursor_even_when_first_page_reaches_reported_count(self):
        one = {'source': 'MED', 'id': '1'}
        two = {'source': 'MED', 'id': '2'}
        with patch.object(updater, 'request_json', side_effect=[response([one], 1, 'next'), response([two], 2)]):
            rows, count = updater.fetch_pages('brain')
        self.assertEqual(rows, [one, two])
        self.assertEqual(count, 2)

    def test_a_cursor_loop_keeps_obtained_rows_and_terminates(self):
        rows = [{'source': 'MED', 'id': '1'}]
        with patch.object(updater, 'request_json', return_value=response(rows, 3, '*')) as api:
            fetched, _ = updater.fetch_pages('brain')
        self.assertEqual(fetched, rows)
        api.assert_called_once()
