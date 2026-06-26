import sqlite3
c=sqlite3.connect('ai_agent/agent_memory.db')
[print(r) for r in c.execute("SELECT id, created_at, json_extract(profile_json,'$.profile_id') AS profile_id FROM weight_versions")]