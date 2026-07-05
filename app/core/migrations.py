import logging
from pathlib import Path

import psycopg2

from app.core.config import settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def run_migrations() -> None:
    database_url = normalize_database_url(settings.DATABASE_URL)
    conn = psycopg2.connect(database_url)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                """
            )
            conn.commit()

            cur.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

            migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
            if not migration_files:
                logger.warning("No migration files found in %s", MIGRATIONS_DIR)
                return

            for path in migration_files:
                version = path.stem
                if version in applied:
                    continue

                logger.info("Applying migration: %s", version)
                sql = path.read_text(encoding="utf-8")

                try:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,),
                    )
                    conn.commit()
                    logger.info("Applied migration: %s", version)
                except Exception:
                    conn.rollback()
                    logger.exception("Failed to apply migration: %s", version)
                    raise
    finally:
        conn.close()
