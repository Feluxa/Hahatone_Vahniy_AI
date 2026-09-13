import os

from alembic import context
from sqlalchemy import create_engine


def run_migrations() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
