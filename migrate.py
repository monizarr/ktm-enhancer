from enhancer.db import connect_db

conn = connect_db()
with conn.cursor() as cur:
    with open("docs/superpowers/specs/enhancement_log.sql") as f:
        cur.execute(f.read())
conn.commit()
conn.close()
print("enhancement_log table created")
