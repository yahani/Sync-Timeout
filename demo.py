"""Member sync demo.

Copies members and their teams from a partner directory API (simulated by
fake_api.py) into a local database. Every API call costs simulated time, and
the sync stops when it runs past its time budget.

    python3 demo.py seed --members 1000 --teams 5
    python3 demo.py sync --budget 60
    python3 demo.py show
    python3 demo.py stats
    python3 demo.py reset
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import fake_api

DB_PATH = Path(__file__).with_name('sync.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    team_id TEXT PRIMARY KEY,
    name    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    member_id TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    team_id   TEXT NOT NULL REFERENCES teams (team_id)
);
CREATE TABLE IF NOT EXISTS sync_state (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    status             TEXT NOT NULL,
    members_synced     INTEGER NOT NULL,
    members_in_api     INTEGER NOT NULL,
    list_members_calls INTEGER NOT NULL,
    get_team_calls     INTEGER NOT NULL,
    simulated_seconds  REAL NOT NULL
);
"""


# --- the sync job ------------------------------------------------------------

def sync_members(conn, api):
    """Copy every member and its team from the API. Commits after each page."""
    page = 1
    while page is not None:
        result = api.list_members(page)
        for member in result['members']:
            try:
                team = api.get_team(member['team_id'])
            except fake_api.NotFound:
                log(f'  skipped {member["member_id"]}: team {member["team_id"]} not found')
                continue
            conn.execute('INSERT OR REPLACE INTO teams (team_id, name) VALUES (?, ?)',
                         (team['team_id'], team['name']))
            conn.execute('INSERT OR REPLACE INTO members (member_id, name, team_id) VALUES (?, ?, ?)',
                         (member['member_id'], member['name'], member['team_id']))
        conn.commit()
        log(f'  page {page}: {len(result["members"])} members, {api.elapsed_seconds:.1f}s simulated so far')
        page = result['next_page']


# --- helpers -----------------------------------------------------------------

def log(message):
    print(message)


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def load_api_data():
    if not fake_api.DATA_PATH.exists():
        sys.exit('no API data yet: run `python3 demo.py seed --members 1000 --teams 5` first')
    return fake_api.load_data()


def count(conn, table):
    return conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]


# --- commands ----------------------------------------------------------------

def cmd_seed(conn, args):
    fake_api.save_data(fake_api.make_data(args.members, args.teams))
    print(f'seeded the partner API with {args.members} members in {args.teams} teams '
          f'({fake_api.PAGE_SIZE} members per page, {fake_api.LATENCY_MS} ms per call)')


def cmd_sync(conn, args):
    data = load_api_data()
    api = fake_api.PartnerAPI(data, budget_seconds=args.budget)
    print(f'=== sync of {len(data["members"])} members, budget {args.budget:g}s ===')
    try:
        sync_members(conn, api)
        status = 'completed'
    except fake_api.TimeBudgetExceeded as exc:
        conn.rollback()  # the page in progress is lost, like a killed job
        status = 'TIMED OUT'
        print(f'  {exc}')

    synced = count(conn, 'members')
    conn.execute('INSERT OR REPLACE INTO sync_state VALUES (1, ?, ?, ?, ?, ?, ?)',
                 (status, synced, len(data['members']), api.calls['list_members'], api.calls['get_team'],
                  api.elapsed_seconds))
    conn.commit()
    print(f'\nStatus:  {status}')
    print(f'Members: {synced} of {len(data["members"])} in the local database')
    print(f'Time:    {api.elapsed_seconds:.1f}s simulated')


def cmd_show(conn, args):
    rows = conn.execute(
        """
        SELECT t.team_id, t.name, COUNT(m.member_id) AS members
        FROM teams t LEFT JOIN members m ON m.team_id = t.team_id
        GROUP BY t.team_id ORDER BY t.team_id
        """
    ).fetchall()
    print('team_id  name       members')
    print('-------  ---------  -------')
    for row in rows:
        print(f'{row["team_id"]:<7}  {row["name"]:<9}  {row["members"]}')
    if not rows:
        print('(none)')
    in_api = len(fake_api.load_data()['members']) if fake_api.DATA_PATH.exists() else '?'
    print(f'\nSynced {count(conn, "members")} of {in_api} members in the API')


def cmd_stats(conn, args):
    row = conn.execute('SELECT * FROM sync_state WHERE id = 1').fetchone()
    if row is None:
        print('no sync has run yet')
        return
    total = row['list_members_calls'] + row['get_team_calls']
    print('Last sync')
    print(f'  status             {row["status"]}')
    print(f'  members synced     {row["members_synced"]} of {row["members_in_api"]}')
    print(f'  list_members calls {row["list_members_calls"]}')
    print(f'  get_team calls     {row["get_team_calls"]}')
    print(f'  total API calls    {total}')
    print(f'  simulated time     {row["simulated_seconds"]:.1f}s ({fake_api.LATENCY_MS} ms per call)')


def cmd_reset(conn, args):
    conn.execute('DELETE FROM members')
    conn.execute('DELETE FROM teams')
    conn.execute('DELETE FROM sync_state')
    conn.commit()
    print('reset: local tables emptied (API data is kept; run seed to replace it)')


# --- CLI ---------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description='Member sync demo')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('seed', help='write the simulated partner API data')
    p.add_argument('--members', type=int, required=True)
    p.add_argument('--teams', type=int, required=True)
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser('sync', help='run the sync job once')
    p.add_argument('--budget', type=float, default=60, help='time budget in simulated seconds (default 60)')
    p.set_defaults(func=cmd_sync)

    sub.add_parser('show', help='synced teams and member counts').set_defaults(func=cmd_show)
    sub.add_parser('stats', help='API calls and time of the last sync').set_defaults(func=cmd_stats)
    sub.add_parser('reset', help='empty the local tables').set_defaults(func=cmd_reset)
    return parser


def main():
    args = build_parser().parse_args()
    conn = connect()
    try:
        args.func(conn, args)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
