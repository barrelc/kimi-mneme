import sys
sys.path.insert(0, '.')

from mneme.db.store import ObservationStore, Observation

store = ObservationStore()
store.add_session('test-sess-1', 'C:/project')

obs = Observation(
    session_id='test-sess-1',
    event_type='PostToolUse',
    tool_name='WriteFile',
    file_path='src/main.py',
    tool_output='Created main entry point',
    tool_input=None,
    error=None,
    prompt=None,
    agent_name=None,
)
obs_id = store.add_observation(obs)
print(f'Added observation #{obs_id}')

stats = store.get_stats()
print(f"Sessions: {stats['total_sessions']}, Observations: {stats['total_observations']}")

results = store.search('main')
print(f"Search 'main': {len(results)} results")
