"""Approved candidate selection only; no feature generation entry point."""
from features.contract import VERSIONS, require, time
from features.observed import select_metadata

def candidates(index):
    output = []
    for uid, rows in sorted(index.by_user['players'].items()):
        player = rows[0]
        for version in VERSIONS:
            calendars = [r for r in index.tables['story_calendar'] if r['version_id'] == version]
            found = []
            for calendar in calendars:
                opened = calendar['region_open_at']
                if time(player['registered_at']) > time(opened):
                    continue
                attr = select_metadata(index.by_user['player_attributes'].get(uid, []), opened, 'attribute')
                if attr['region_id'] != calendar['region_id']:
                    continue
                require(time(player['available_at']) <= time(opened) and time(calendar['available_at']) <= time(opened), 'candidate_metadata', uid)
                found.append({'user_id': uid, 'story_id': calendar['story_id'], 'version_id': version, 'region_open_at': opened, 'region_id': attr['region_id']})
            require(len(found) <= 1, 'duplicate_candidate', f'{uid}/{version}')
            output.extend(found)
    return sorted(output, key=lambda r: (r['version_id'], r['user_id'], r['story_id']))
