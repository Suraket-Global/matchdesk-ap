"""Alembic environment. Migrations run as the table owner, never as the application role."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, text

from matchdesk.core import load_settings
from matchdesk.schema_registry import load_all_models

target_metadata = load_all_models().metadata


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # The queue and Alembic's own table are outside ORM parity.
    return not (type_ == "table" and name == "alembic_version")


def run_migrations_online() -> None:
    url = context.config.get_main_option("sqlalchemy.url") or load_settings().migration_database_url
    engine = create_engine(url)
    with engine.connect() as connection:
        # Lock rules of schema.md section 9 (R-11).
        connection.execute(text("set lock_timeout = '5s'"))
        connection.execute(text("set statement_timeout = '15min'"))
        # Session settings survive this commit; Alembic then owns the migration transaction, which
        # lets a migration build an index concurrently in ``autocommit_block()`` (B9, 0019).
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


run_migrations_online()
