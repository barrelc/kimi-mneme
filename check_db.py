import sqlite3

conn = sqlite3.connect('mneme.db')
cursor = conn.cursor()

# Таблицы
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('=== ТАБЛИЦЫ ===')
tables = cursor.fetchall()
for t in tables:
    print(f'  {t[0]}')

if not tables:
    print('  (нет таблиц)')
    conn.close()
    exit()

# Для каждой таблицы — структура и количество
for (table_name,) in tables:
    print(f'\n=== {table_name} ===')
    cursor.execute(f'PRAGMA table_info({table_name})')
    for col in cursor.fetchall():
        print(f'  {col[1]} ({col[2]})')
    
    cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
    count = cursor.fetchone()[0]
    print(f'  Записей: {count}')
    
    if count > 0 and table_name in ['observations', 'raw_observations', 'structured_observations']:
        cursor.execute(f'SELECT * FROM {table_name} LIMIT 1')
        row = cursor.fetchone()
        cursor.execute(f'PRAGMA table_info({table_name})')
        cols = [c[1] for c in cursor.fetchall()]
        print(f'  Пример записи:')
        for i, val in enumerate(row):
            v = str(val)[:80] if val is not None else 'NULL'
            print(f'    {cols[i]}: {v}')

conn.close()
