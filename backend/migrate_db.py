import sqlite3

conn = sqlite3.connect("synesis.db")
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(meetings)")
columns = [col[1] for col in cursor.fetchall()]
print("Existing columns:", columns)

if "workspace_id" not in columns:
    print("Adding workspace_id column...")
    cursor.execute("ALTER TABLE meetings ADD COLUMN workspace_id VARCHAR(64) DEFAULT 'ws_default'")

if "source_connection_id" not in columns:
    print("Adding source_connection_id column...")
    cursor.execute("ALTER TABLE meetings ADD COLUMN source_connection_id VARCHAR(64)")

conn.commit()
print("Migration complete!")
