import os
import sys
import glob
import psycopg2
from dotenv import load_dotenv

# SafeRoute API custom migration runner.
#
# This is a lightweight alternative to the Supabase CLI migration system.
# It supports both:
#   - Numbered migrations: migrations/001_add_users_table.sql
#   - Timestamped migrations: migrations/20240101_120000_add_users_table.sql
#
# For local development with Supabase CLI, prefer:
#   supabase migration new <description>
#   supabase migration up
#
# The Supabase CLI stores migration state in supabase/migrations/ and uses
# the project's meta-database. This runner is intended for CI/CD or
# environments where the CLI is not installed.

def run_migrations():
    load_dotenv()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set. Cannot run migrations.")
        sys.exit(1)

    print("Connecting to database...")
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            # Create migrations table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
                )
            """)
            conn.commit()

            # Find all migration files
            migration_files = sorted(glob.glob("migrations/*.sql"))
            if not migration_files:
                print("No migration files found in migrations/ directory.")
                return

            for filepath in migration_files:
                filename = os.path.basename(filepath)
                # Check if already applied
                cur.execute("SELECT version FROM schema_migrations WHERE version = %s", (filename,))
                if cur.fetchone():
                    print(f"Skipping {filename} (already applied)")
                    continue

                print(f"Applying {filename}...")
                with open(filepath, "r", encoding="utf-8") as f:
                    sql = f.read()

                try:
                    cur.execute(sql)
                    cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (filename,))
                    conn.commit()
                    print(f"Successfully applied {filename}")
                except Exception as e:
                    conn.rollback()
                    print(f"Error applying {filename}: {e}")
                    sys.exit(1)

    finally:
        conn.close()

if __name__ == "__main__":
    run_migrations()
