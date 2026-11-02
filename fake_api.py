"""Simulated partner directory API.

The data lives in api_data.json (written by `demo.py seed`). Nothing goes over
the network: every call adds LATENCY_MS to a simulated clock, and once the clock
passes the budget the call raises TimeBudgetExceeded, like a job being stopped
by its scheduler.
"""
import json
from pathlib import Path

DATA_PATH = Path(__file__).with_name('api_data.json')
LATENCY_MS = 100
PAGE_SIZE = 100


class NotFound(Exception):
    pass


class TimeBudgetExceeded(Exception):
    pass


def make_data(members, teams):
    """Members M0001.. spread round-robin over teams T1..Tn."""
    return {
        'teams': {f'T{t}': {'team_id': f'T{t}', 'name': f'Team {t}'} for t in range(1, teams + 1)},
        'members': [{'member_id': f'M{i:04d}', 'name': f'Member {i}', 'team_id': f'T{(i - 1) % teams + 1}'}
                    for i in range(1, members + 1)],
    }


def save_data(data, path=DATA_PATH):
    path.write_text(json.dumps(data, indent=1))


def load_data(path=DATA_PATH):
    return json.loads(path.read_text())


class PartnerAPI:
    def __init__(self, data, budget_seconds=None):
        self.data = data
        self.budget_ms = None if budget_seconds is None else budget_seconds * 1000
        self.elapsed_ms = 0
        self.calls = {'list_members': 0, 'get_team': 0}

    @property
    def elapsed_seconds(self):
        return self.elapsed_ms / 1000

    def _charge(self, endpoint):
        self.calls[endpoint] += 1
        self.elapsed_ms += LATENCY_MS
        if self.budget_ms is not None and self.elapsed_ms > self.budget_ms:
            raise TimeBudgetExceeded(f'time budget of {self.budget_ms / 1000:g}s exceeded '
                                     f'on call {sum(self.calls.values())} ({endpoint})')

    def list_members(self, page):
        """One page of members; next_page is None on the last page."""
        self._charge('list_members')
        start = (page - 1) * PAGE_SIZE
        members = self.data['members'][start:start + PAGE_SIZE]
        next_page = page + 1 if start + PAGE_SIZE < len(self.data['members']) else None
        return {'members': [dict(m) for m in members], 'next_page': next_page}

    def get_team(self, team_id):
        self._charge('get_team')
        team = self.data['teams'].get(team_id)
        if team is None:
            raise NotFound(team_id)
        return dict(team)
