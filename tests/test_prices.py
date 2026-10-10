import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prices_updater', Path(__file__).resolve().parents[1] / 'scripts/update_data.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)

class PriceTests(unittest.TestCase):
    def test_both_providers_accept_short_history_only_when_allowed(self):
        for fetch, payload in [
            (u.fetch_alpha_vantage, {'Weekly Adjusted Time Series': {'2026-10-09': {'5. adjusted close': '30'}, '2026-10-02': {'5. adjusted close': '10'}}}),
            (u.fetch_tiingo, [{'date': '2026-10-02', 'adjClose': 10}, {'date': '2026-10-09', 'adjClose': 30}]),
        ]:
            with self.subTest(provider=fetch.__name__):
                with patch.object(u.urllib.request, 'urlopen', return_value=io.StringIO(json.dumps(payload))):
                    with self.assertRaises(u.InsufficientHistory): fetch('A', 'key')
                with patch.object(u.urllib.request, 'urlopen', return_value=io.StringIO(json.dumps(payload))):
                    result = fetch('A', 'key', allow_short_history=True)
                self.assertEqual((result['price'], result['sma200'], result['weeks']), (30, 20, 2))

    def test_empty_wishlist_history_is_an_error(self):
        with patch.object(u.urllib.request, 'urlopen', return_value=io.StringIO('[]')):
            with self.assertRaisesRegex(RuntimeError, 'No weekly prices'): u.fetch_tiingo('A', 'key', True)

    def test_refresh_bypasses_retry_and_removes_old_insufficient_record(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.ExitStack() as stack:
            root = Path(folder)
            files = {'SYMBOLS_FILE': [['N', 'Nasdaq']], 'SP500_FILE': [['S', 'Legacy']], 'WATCHLIST_FILE': ['Y'], 'BLACKLIST_FILE': [], 'OUTPUT_FILE': {'stocks': [], 'insufficient_history': [{'symbol': 'Y', 'weeks': 2, 'retry_after': '2099-01-01'}]}, 'STATE_FILE': {}}
            for attr, data in files.items():
                path = root / (attr + '.json')
                path.write_text(json.dumps(data))
                stack.enter_context(patch.object(u, attr, path))
            stack.enter_context(patch.dict(os.environ, {'ALPHA_VANTAGE_API_KEYS': 'key', 'DAILY_LIMIT': '2', 'TIINGO_API_KEY': ''}))
            stack.enter_context(patch('sys.argv', ['update_data.py', '--rescan-wishlist']))
            stack.enter_context(patch.object(u.time, 'sleep'))
            fetch = stack.enter_context(patch.object(u, 'fetch_alpha_vantage', return_value={'price': 30, 'sma200': 20, 'weeks': 2, 'updated': '2026-10-09'}))
            u.main()
            self.assertEqual([call.args[0] for call in fetch.call_args_list], ['Y', 'N'])
            self.assertTrue(fetch.call_args_list[0].kwargs['allow_short_history'])
            self.assertFalse(fetch.call_args_list[1].kwargs['allow_short_history'])
            saved = json.loads(u.OUTPUT_FILE.read_text())
            self.assertEqual(saved['insufficient_history'], [])
            self.assertEqual(saved['stocks'][0]['distance'], 50)

if __name__ == '__main__': unittest.main()
