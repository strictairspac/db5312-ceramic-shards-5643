from sqlalchemy import inspect, text

from src.models.tables import schema

# Columns added after the initial schema. ``create_all`` only creates missing
# tables, so an existing demo volume needs these applied explicitly.
ADDED_COLUMNS = {
    'business_cases': {
        'revision': 'INT NOT NULL DEFAULT 1',
    },
    'business_runs': {
        'revision': 'INT NULL',
    },
    'business_evidence': {
        'revision': 'INT NULL',
        'state': "VARCHAR(20) NOT NULL DEFAULT 'valid'",
        'voided_at': 'VARCHAR(32) NULL',
        'void_reason': 'VARCHAR(200) NULL',
    },
}


def ensure_schema(engine):
    schema.create_all(engine)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {column['name'] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name in present:
                    continue
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
        # Legacy evidence predates corrections and is treated as valid for its own revision.
        if 'business_evidence' in existing_tables:
            conn.execute(text("UPDATE business_evidence SET state = 'valid' WHERE state IS NULL"))
