import sqlite3
import os

db_path = os.path.join('instance', 'studybyte_v5.db')
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}, trying current dir...")
    db_path = 'studybyte_v5.db'

print(f"Using DB at {db_path}")

try:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("ALTER TABLE topic_listing ADD COLUMN is_advertised BOOLEAN DEFAULT 0")
    conn.commit()
    print("Column added successfully.")
except Exception as e:
    print(f"Error: {e}")
finally:
    if 'conn' in locals():
        conn.close()
