import sqlite3
from pathlib import Path

db_path = Path.home() / '.kimi/mneme/mneme.db'
conn = sqlite3.connect(str(db_path))

# Check if our session exists
rows = conn.execute("SELECT id FROM sessions WHERE id = '6fc71b7c-8616-4ab5-a5b0-b5f71b3f9b94'").fetchall()
print('Session found:', len(rows) > 0)

# Count observations for this session
obs = conn.execute("SELECT COUNT(*) FROM observations WHERE session_id = '6fc71b7c-8616-4ab5-a5b0-b5f71b3f9b94'").fetchone()
print('Observations for 6fc71b7c:', obs[0])

# Show all sessions
print('\nAll sessions:')
for r in conn.execute('SELECT id, started_at FROM sessions ORDER BY started_at DESC LIMIT 10').fetchall():
    print(' ', r[0][:8], r[1])

conn.close()
