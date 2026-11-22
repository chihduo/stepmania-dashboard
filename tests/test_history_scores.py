import copy
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_dashboard as sync


class PreservedScoreTests(unittest.TestCase):
    def score(self, guid=None):
        score = {"dt": "2026-11-12 12:00:00", "pct": 0.9, "grade": "Tier03",
                 "sc": 900, "co": 80, "sv": 120.0, "j": [90, 10, 0, 0, 0, 0]}
        if guid:
            score["id"] = guid
        return score

    def test_legacy_to_event_overlap_is_one_record(self):
        scores = [self.score('event')]
        self.assertEqual(sync.merge_preserved_scores(scores, [self.score()]), 0)
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0]['id'], 'event')

    def test_published_event_id_upgrades_matching_legacy_record(self):
        scores = [self.score()]
        self.assertEqual(sync.merge_preserved_scores(scores, [self.score('event')]), 0)
        self.assertEqual(scores, [self.score('event')])

    def test_distinct_ids_with_identical_scores_survive(self):
        scores = [self.score('a')]
        self.assertEqual(sync.merge_preserved_scores(scores, [self.score('b')]), 1)
        self.assertEqual({score['id'] for score in scores}, {'a', 'b'})
        self.assertEqual(sync.merge_preserved_scores(scores, [self.score('a'), self.score('b')]), 0)

    def test_legacy_multiplicity_is_preserved_without_retry_duplicates(self):
        scores = [self.score()]
        history = [self.score(), self.score()]
        self.assertEqual(sync.merge_preserved_scores(scores, history), 1)
        self.assertEqual(sync.merge_preserved_scores(scores, history), 0)
        self.assertEqual(len(scores), 2)

    def test_exact_id_is_reserved_before_matching_legacy_score(self):
        scores = [self.score('b')]
        history = [self.score(), self.score('b')]
        self.assertEqual(sync.merge_preserved_scores(scores, history), 1)
        self.assertEqual(len(scores), 2)
        self.assertEqual(sync.merge_preserved_scores(scores, history), 0)

    def test_same_id_with_changed_score_is_rejected(self):
        scores = [self.score('a')]
        changed = self.score('a'); changed['sc'] = 800
        with self.assertRaisesRegex(ValueError, 'Historical score changed'):
            sync.merge_preserved_scores(scores, [changed])

    def test_recovered_record_does_not_mutate_published_source(self):
        history = [self.score()]
        before = copy.deepcopy(history)
        scores = []
        sync.merge_preserved_scores(scores, history)
        scores[0]['j'][0] = 1
        self.assertEqual(history, before)


if __name__ == '__main__':
    unittest.main()
