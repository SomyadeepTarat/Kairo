"""Versioned PostgreSQL migrations; test schema selection is explicit and validated."""

import os
import re

from alembic import context
from kairo_core.persistence.tables import Base
from sqlalchemy import create_engine, pool, text

config = context.config
url = os.environ.get("KAIRO_DATABASE_URL")
if not url or not url.startswith("postgresql+psycopg://"):
    raise ValueError("Set KAIRO_DATABASE_URL to a postgresql+psycopg:// URL")
schema = config.attributes.get("schema", "public")
if not isinstance(schema, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", schema):
    raise ValueError("Invalid migration schema")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool, connect_args={"connect_timeout": 5})
    with engine.connect() as connection:
        if schema != "public":
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
        # The session search_path already selects the isolated schema. Let
        # Alembic treat its version table as belonging to that default schema,
        # matching reflection/autogenerate's unqualified table names.
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
