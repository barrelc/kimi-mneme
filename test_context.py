import json
from pathlib import Path

session_id = '6fc71b7c-8616-4ab5-a5b0-b5f71b3f9b94'
sessions_dir = Path.home() / '.kimi' / 'sessions'

for hash_dir in sessions_dir.iterdir():
    if not hash_dir.is_dir():
        continue
    session_dir = hash_dir / session_id
    if session_dir.exists():
        context_file = session_dir / 'context.jsonl'
        if context_file.exists():
            print('Found:', context_file)
            lines = context_file.read_text(encoding='utf-8').strip().split('\n')
            print('Total lines:', len(lines))
            for line in reversed(lines[-5:]):
                try:
                    event = json.loads(line)
                    role = event.get('role')
                    if role == 'user':
                        content = event.get('content', [])
                        if isinstance(content, list):
                            for part in content:
                                if part.get('type') == 'text':
                                    print('USER:', part.get('text', ''))
                        elif isinstance(content, str):
                            print('USER:', content)
                except Exception as e:
                    print('Error:', e)
        break
