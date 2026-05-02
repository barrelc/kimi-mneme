# Privacy Guide

kimi-mneme takes privacy seriously. By default, sensitive content is excluded from storage.

## Automatic Exclusions

The following patterns are automatically excluded:

- Files matching: `*.env*`, `*.env.local`, `*secret*`, `*password*`, `*token*`, `*api_key*`, `*private_key*`
- Content longer than 100,000 characters (truncated)

## Privacy Tags

Wrap sensitive content in privacy tags to exclude it from storage:

```
User: Here's my database password: <private>super_secret_123</private>
```

The tag and its contents are replaced with `[PRIVATE]` before storage.

Supported tags (configurable):
- `<private>...</private>`
- `<secret>...</secret>`

## Custom Exclusion Patterns

Add to `~/.kimi/mneme/config.json`:

```json
{
  "privacy": {
    "exclude_patterns": [
      "*.local.env",
      "secrets/*",
      "*.pem",
      "*.key",
      "*credential*"
    ]
  }
}
```

## What Gets Stored

| Data | Stored? | Notes |
|------|---------|-------|
| File paths | ✅ Yes | Relative paths preferred |
| Tool names | ✅ Yes | ReadFile, WriteFile, Shell, etc. |
| Tool outputs (success) | ✅ Yes | Sanitized |
| Tool outputs (errors) | ✅ Yes | Helps learn from mistakes |
| User prompts | ✅ Yes | Intent and context |
| File contents | ⚠️ Partial | Only paths, not full content |
| API keys | ❌ No | Automatically excluded |
| Passwords | ❌ No | Automatically excluded |
| `<private>` blocks | ❌ No | Replaced with `[PRIVATE]` |

## Data Location

All data is stored locally:

```
~/.kimi/mneme/
├── mneme.db          # SQLite database
├── chroma/           # Vector database
├── config.json       # Configuration
├── backups/          # Automatic backups
└── mneme.log         # Log file
```

Nothing is sent to external servers except:
- AI compression (if enabled, sent to Moonshot API)
- You control the API key and can disable compression

## Disabling Compression

To keep everything 100% local:

```json
{
  "compression": {
    "enabled": false
  }
}
```

Without compression, raw observations are stored. Search still works via full-text and vector search on raw content.

## Deleting Data

```bash
# Delete all data
rm -rf ~/.kimi/mneme

# Delete specific session
python -m mneme.db.delete --session-id sess_abc123

# Delete observations older than 30 days
python -m mneme.db.cleanup --days 30
```

## Encryption (Optional)

For additional security, enable SQLite encryption:

```json
{
  "db": {
    "encryption": {
      "enabled": true,
      "key": "${MNEME_DB_KEY}"
    }
  }
}
```

Requires `sqlcipher` or `pysqlcipher3`.
