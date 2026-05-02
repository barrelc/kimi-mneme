import sys
sys.path.insert(0, '.')

from mneme.db.store import ObservationStore, Observation

store = ObservationStore()

# Add sessions with different projects
sessions = [
    ('sess-psa-1', 'C:/Users/barre/Desktop/psa-saas-work'),
    ('sess-psa-2', 'C:/Users/barre/Desktop/psa-saas-work'),
    ('sess-game-1', 'C:/Users/barre/games/space-shooter'),
    ('sess-game-2', 'C:/Users/barre/games/space-shooter'),
    ('sess-api-1', 'C:/Users/barre/backend-api'),
]

for sid, cwd in sessions:
    store.add_session(sid, cwd)
    obs = Observation(
        session_id=sid,
        event_type='PostToolUse',
        tool_name='WriteFile',
        file_path='src/main.py',
        tool_output=f'Created feature in {cwd}'
    )
    store.add_observation(obs)

print('Test data added:')
for s in store.get_sessions(limit=100):
    print(f"  {s['cwd']}: {s['observation_count']} obs")
