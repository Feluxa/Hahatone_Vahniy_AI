from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    root = Path(__file__).resolve().parents[3]
    connection = op.get_bind().connection.driver_connection
    for path in sorted((root / "sql").glob("*.sql")):
        if int(path.name.split("_", 1)[0]) >= 90:
            continue
        with connection.cursor() as cursor:
            cursor.execute(path.read_text(encoding="utf-8"), prepare=False)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; recreate the disposable development database")
