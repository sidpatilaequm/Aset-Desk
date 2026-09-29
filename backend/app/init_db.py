"""Create the MySQL tables from database/schema.sql.  Usage:  python -m app.init_db"""
from pathlib import Path
from sqlalchemy import text
from .db import engine

SCHEMA = Path(__file__).resolve().parents[2] / "database" / "schema.sql"


def main():
    lines = [l for l in SCHEMA.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--")]
    statements = [s.strip() for s in "\n".join(lines).split(";\n") if s.strip()]
    with engine.begin() as conn:
        for st in statements:
            conn.execute(text(st.rstrip(";")))
    print(f"Applied {len(statements)} statements from {SCHEMA.name}")


if __name__ == "__main__":
    main()
