import sqlite3
import unittest
from unittest import mock

import demo
import fake_api

sync = demo.sync_members

# python3 -m unittest -v 2>&1 | tee test_results_before.txt
# python3 -m unittest -v 2>&1 | tee test_results_after.txt


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch('demo.log'))  # keep test output clean
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(demo.SCHEMA)

    def tearDown(self):
        self.conn.close()

    def run_sync(self, data, budget_seconds=None):
        api = fake_api.PartnerAPI(data, budget_seconds)
        sync(self.conn, api)
        return api

    def member_teams(self):
        return {r['member_id']: r['team_id'] for r in self.conn.execute('SELECT * FROM members')}

    def team_names(self):
        return {r['team_id']: r['name'] for r in self.conn.execute('SELECT * FROM teams')}

    def test_sync_of_1000_members_finishes_within_the_budget(self):
        try:
            self.run_sync(fake_api.make_data(members=1000, teams=5), budget_seconds=60)
        except fake_api.TimeBudgetExceeded as exc:
            self.fail(f'sync timed out: {exc}')

        self.assertEqual(len(self.member_teams()), 1000)

    def test_each_team_is_fetched_at_most_once_per_run(self):
        api = self.run_sync(fake_api.make_data(members=300, teams=5))

        self.assertLessEqual(api.calls['get_team'], 5)

    def test_every_member_gets_the_right_team(self):
        data = fake_api.make_data(members=12, teams=3)
        self.run_sync(data)

        self.assertEqual(self.member_teams(), {m['member_id']: m['team_id'] for m in data['members']})
        self.assertEqual(self.team_names(), {'T1': 'Team 1', 'T2': 'Team 2', 'T3': 'Team 3'})

    def test_renamed_team_is_picked_up_on_the_next_run(self):
        data = fake_api.make_data(members=10, teams=2)
        self.run_sync(data)
        data['teams']['T1']['name'] = 'Renamed'
        self.run_sync(data)

        self.assertEqual(self.team_names()['T1'], 'Renamed')

    def test_member_with_missing_team_is_skipped_and_the_rest_are_synced(self):
        data = fake_api.make_data(members=10, teams=2)
        data['members'][3]['team_id'] = 'T99'
        self.run_sync(data)

        members = self.member_teams()
        self.assertNotIn('M0004', members)
        self.assertEqual(len(members), 9)

    def test_rerun_does_not_duplicate_rows(self):
        data = fake_api.make_data(members=10, teams=2)
        self.run_sync(data)
        self.run_sync(data)

        self.assertEqual(len(self.member_teams()), 10)
        self.assertEqual(len(self.team_names()), 2)


if __name__ == '__main__':
    unittest.main()
