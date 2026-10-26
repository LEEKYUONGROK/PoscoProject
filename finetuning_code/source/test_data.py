import json
import unittest
import pandas as pd
from prepare import build
from evaluate import checks


class DataTests(unittest.TestCase):
    def test_reference_grounded_in_computed_metrics(self):
        row = {'case': 'x', 'inject_time': 300, 'root_cause_service': 'svc',
               'fault': 'cpu', 'fault_description': 'CPU stress', 'system_name': 'test'}
        frame = pd.DataFrame({'time': [0, 299, 300, 599, 600],
                              'svc_cpu': [1., 3., 10., 20., 9999.]})
        item = build(row, frame)
        self.assertIn('baseline median=2; incident median=15; incident max=20', item['source']['evidence'][0])
        self.assertTrue(checks(json.dumps(item['reference']), item)['all_checks'])
        bad = dict(item['reference'], evidence=['invented metric'])
        self.assertFalse(checks(json.dumps(bad), item)['evidence'])
        bad = dict(item['reference'], confidence=0.99)
        self.assertFalse(checks(json.dumps(bad), item)['all_checks'])

    def test_missing_window_rejected(self):
        with self.assertRaises(ValueError):
            build({'inject_time': 300}, pd.DataFrame({'time': [0]}))


if __name__ == '__main__':
    unittest.main()
