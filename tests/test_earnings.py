import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('updater', Path(__file__).resolve().parents[1] / 'scripts/update_data.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)

class EarningsTests(unittest.TestCase):
    def test_append_preserves_original_and_catches_up(self):
        today = dt.date(2026, 10, 3)
        record = {}
        def row(end, eps): return {'fiscal_date_ending': end, 'eps': eps}
        u.append_earnings(record, [row('2026-03-31', 1), row('2026-06-30', 2)], today)
        self.assertEqual([r['eps'] for r in record['quarters']], [2])
        u.append_earnings(record, [row('2026-06-30', 99), row('2026-09-30', -1), row('2026-12-31', 0)], today)
        self.assertEqual([r['eps'] for r in record['quarters']], [2, -1, 0])

    def test_quota_cache_blacklist_and_failed_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'earnings.json'
            today = dt.date(2026, 10, 3)
            with patch.object(u, 'EARNINGS_FILE', path), patch.object(u.time, 'sleep'), patch.object(u, 'fetch_earnings', return_value=[{'fiscal_date_ending': '2026-06-30', 'eps': 2, 'eps_ttm': 8}]) as fetch:
                used, counts, key = u.update_earnings(['A', 'B'], {'B'}, ['key'], 1, today)
                self.assertEqual((used, counts, key), (1, [1], 0))
                fetch.assert_called_once_with('A', 'key')
                self.assertEqual(u.update_earnings(['A'], set(), ['key'], 5, today)[0], 0)
                fetch.side_effect = RuntimeError('temporary failure')
                u.update_earnings(['A'], set(), ['key'], 5, today + dt.timedelta(days=7))
                saved = json.loads(path.read_text())['stocks']['A']
                self.assertEqual(saved['quarters'][0]['eps'], 2)
                self.assertEqual(saved['error'], 'temporary failure')

    def test_valuation_retains_history_and_handles_losses_and_stale_prices(self):
        today=dt.date(2026,10,3)
        record={"quarters":[{"fiscal_date_ending":"2026-06-30","reported_date":"2026-07-23","eps":2,"eps_ttm":8}]}
        self.assertFalse(u.append_valuation(record,{"price":80,"updated":"2026-07-01"},today))
        self.assertTrue(u.append_valuation(record,{"price":80,"updated":"2026-10-01"},today))
        self.assertEqual(record["valuations"][0]["pe"],40)
        self.assertFalse(u.append_valuation(record,{"price":160,"updated":"2026-10-02"},today))
        self.assertEqual(record["valuations"][0]["price"],80)
        record["quarters"].append({"fiscal_date_ending":"2026-09-30","eps":-2})
        self.assertTrue(u.append_valuation(record,{"price":80,"updated":"2026-10-08"},today+dt.timedelta(days=7)))
        self.assertEqual(record["valuations"][-1]["pe"],-40)
        self.assertFalse(u.append_valuation(record,{"price":100,"updated":"2026-10-09"},today+dt.timedelta(days=8)))

    def test_fetch_calculates_ttm_from_four_consecutive_quarters(self):
        import io
        payload={"quarterlyEarnings":[{"fiscalDateEnding":date,"reportedEPS":str(eps)} for date,eps in [("2026-06-30",4),("2026-03-31",3),("2025-12-31",2),("2025-09-30",1)]]}
        with patch.object(u.urllib.request,"urlopen",return_value=io.StringIO(json.dumps(payload))):
            rows=u.fetch_earnings("A","test-key")
        self.assertEqual(rows[-1]["eps_ttm"],10)
        self.assertNotIn("eps_ttm",rows[0])

    def test_earnings_only_leaves_prices_and_rotation_unchanged(self):
        prices=u.OUTPUT_FILE.read_bytes()
        rotation=u.STATE_FILE.read_bytes()
        with patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY":"test-key", "ALPHA_VANTAGE_API_KEYS":"", "DAILY_LIMIT":"25"}), patch('sys.argv', ['update_data.py', '--earnings-only']), patch.object(u, 'update_earnings', return_value=(17,[17],0)) as update, patch.object(u, 'fetch_alpha_vantage') as prices_fetch, patch.object(u, 'fetch_tiingo') as tiingo_fetch:
            u.main()
            self.assertEqual(update.call_args.args[3],25)
            prices_fetch.assert_not_called()
            tiingo_fetch.assert_not_called()
        self.assertEqual(u.OUTPUT_FILE.read_bytes(),prices)
        self.assertEqual(u.STATE_FILE.read_bytes(),rotation)

    def test_per_key_request_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(u,'EARNINGS_FILE',Path(folder)/'earnings.json'),patch.object(u.time,'sleep'),patch.object(u,'fetch_earnings',return_value=[{"fiscal_date_ending":"2026-06-30","eps":1,"eps_ttm":4}]) as fetch:
                used,counts,_=u.update_earnings([f"A{i}" for i in range(26)],set(),['key1','key2'],50,dt.date(2026,10,3))
                self.assertEqual((used,counts),(26,[25,1]))
                self.assertEqual(fetch.call_args.args[1],'key2')

    def test_rate_limit_marks_key_unavailable_without_losing_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'earnings.json'
            with patch.object(u, 'EARNINGS_FILE', path), patch.object(u.time, 'sleep'), patch.object(u, 'fetch_earnings', side_effect=RuntimeError('25 requests rate limit')):
                self.assertEqual(u.update_earnings(['A'], set(), ['key'], 5, dt.date(2026, 10, 3)), (25, [25], 1))
                self.assertEqual(json.loads(path.read_text())['stocks'], {})

if __name__ == '__main__': unittest.main()
