import datetime as dt
import importlib.util
import json
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
            with patch.object(u, 'EARNINGS_FILE', path), patch.object(u.time, 'sleep'), patch.object(u, 'fetch_earnings', return_value=[{'fiscal_date_ending': '2026-06-30', 'eps': 2}]) as fetch:
                used, counts, key = u.update_earnings(['A', 'B'], {'B'}, ['key'], 1, today)
                self.assertEqual((used, counts, key), (1, [1], 0))
                fetch.assert_called_once_with('A', 'key')
                self.assertEqual(u.update_earnings(['A'], set(), ['key'], 5, today)[0], 0)
                fetch.side_effect = RuntimeError('temporary failure')
                u.update_earnings(['A'], set(), ['key'], 5, today + dt.timedelta(days=7))
                saved = json.loads(path.read_text())['stocks']['A']
                self.assertEqual(saved['quarters'][0]['eps'], 2)
                self.assertEqual(saved['error'], 'temporary failure')

    def test_rate_limit_marks_key_unavailable_without_losing_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'earnings.json'
            with patch.object(u, 'EARNINGS_FILE', path), patch.object(u.time, 'sleep'), patch.object(u, 'fetch_earnings', side_effect=RuntimeError('25 requests rate limit')):
                self.assertEqual(u.update_earnings(['A'], set(), ['key'], 5, dt.date(2026, 10, 3)), (25, [25], 1))
                self.assertEqual(json.loads(path.read_text())['stocks'], {})

if __name__ == '__main__': unittest.main()
