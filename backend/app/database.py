from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


database_url = settings.database_url
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema(bind: Engine | Connection | None = None) -> None:
    """Idempotent schema upgrade for databases created before a model change.

    ``create_all`` only creates missing tables, so databases that already exist
    need new columns, indexes, and backfills applied explicitly. Safe to call
    repeatedly from startup and from alembic revision 0003. When ``bind`` is a
    Connection the caller owns the transaction; otherwise one is opened here.
    """
    if bind is None:
        with engine.begin() as connection:
            _upgrade_schema(connection)
    elif isinstance(bind, Engine):
        with bind.begin() as connection:
            _upgrade_schema(connection)
    else:
        _upgrade_schema(bind)


def _upgrade_schema(connection: Connection) -> None:
    from . import models  # noqa: F401
    from .models import DEFAULT_CHAIN_KEY, DEFAULT_CHAIN_NAME

    Base.metadata.create_all(bind=connection)
    inspector = sa_inspect(connection)
    tables = set(inspector.get_table_names())
    if "supply_chain_nodes" not in tables or "supply_chains" not in tables:
        return
    dialect = inspector.dialect.name

    node_columns = {column["name"] for column in inspector.get_columns("supply_chain_nodes")}
    missing_columns: dict[str, str] = {
        "chain_id": "INTEGER REFERENCES supply_chains(id)",
        "verified_at": "DATETIME",
        "verified_by": "INTEGER REFERENCES users(id)",
    }
    for name, column_type in missing_columns.items():
        if name in node_columns:
            continue
        if dialect == "postgresql":
            connection.exec_driver_sql(f"ALTER TABLE supply_chain_nodes ADD COLUMN IF NOT EXISTS {name} {column_type}")
        else:
            connection.exec_driver_sql(f"ALTER TABLE supply_chain_nodes ADD COLUMN {name} {column_type}")

    # Guarantee a default chain exists, then adopt any unscoped nodes into it.
    connection.execute(
        text(
            "INSERT INTO supply_chains (key, name, description, status, created_at, updated_at) "
            "SELECT :key, :name, :description, 'active', :now, :now "
            "WHERE NOT EXISTS (SELECT 1 FROM supply_chains)"
        ),
        {"key": DEFAULT_CHAIN_KEY, "name": DEFAULT_CHAIN_NAME, "description": "Default demo supply chain.", "now": models.utcnow()},
    )
    connection.execute(
        text("UPDATE supply_chain_nodes SET chain_id = (SELECT id FROM supply_chains ORDER BY id LIMIT 1) WHERE chain_id IS NULL")
    )
    if dialect == "postgresql":
        connection.exec_driver_sql("ALTER TABLE supply_chain_nodes ALTER COLUMN chain_id SET NOT NULL")

    indexes = inspector.get_indexes("supply_chain_nodes")
    index_names = {index["name"] for index in indexes}
    for index in indexes:
        if index.get("unique") and list(index.get("column_names") or []) == ["key"]:
            connection.exec_driver_sql(f'DROP INDEX IF EXISTS "{index["name"]}"')
            index_names.discard(index["name"])
    wanted = {
        "ix_supply_chain_nodes_key": 'CREATE INDEX IF NOT EXISTS ix_supply_chain_nodes_key ON supply_chain_nodes ("key")',
        "ix_supply_chain_nodes_chain_id": "CREATE INDEX IF NOT EXISTS ix_supply_chain_nodes_chain_id ON supply_chain_nodes (chain_id)",
        "uq_supply_chain_node_key": 'CREATE UNIQUE INDEX IF NOT EXISTS uq_supply_chain_node_key ON supply_chain_nodes (chain_id, "key")',
    }
    for name, statement in wanted.items():
        if name not in index_names:
            connection.exec_driver_sql(statement)


def init_db() -> None:
    ensure_schema(engine)
