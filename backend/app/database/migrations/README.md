# Alembic migrations

`scripts/setup_db.py` / `init_db()` create tables directly via `metadata.create_all`,
which is fine for local dev. For production schema changes use Alembic:

```bash
# from the backend/ directory
alembic -c app/database/migrations/alembic.ini revision --autogenerate -m "add payments table"
alembic -c app/database/migrations/alembic.ini upgrade head
```

The `env.py` in this folder reads `DATABASE_URL` from app settings, so there is no
need to edit `sqlalchemy.url` inside the ini file.
