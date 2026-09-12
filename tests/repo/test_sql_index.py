"""Индекс SQL-объектов (PLAN §5.3).

Разбор регулярками, а не полноценным парсером: нужны имена, сигнатуры и номера строк, чтобы №2
знал схему и контракты таблиц. Главная тонкость — тела функций (`$tag$ ... $tag$`) и комментарии
вырезаются до разбора, иначе `CREATE`/`INSERT` внутри тела превратились бы в объявления.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.contracts import SqlObject
from harness.repo.sql_index import index_sql
from tests.repo.tiny_repo import build_repo

MERIDIAN = Path(__file__).resolve().parents[2] / "materials" / "hackathon-participants" / "meridian"
needs_meridian = pytest.mark.skipif(not MERIDIAN.is_dir(), reason="materials/ не выложены локально")

SCHEMA_SQL = b"""CREATE SCHEMA IF NOT EXISTS shop;

-- CREATE TABLE shop.commented_out (x int);
/* CREATE VIEW shop.block_comment AS SELECT 1; */

CREATE TABLE shop.item (
    item_id text NOT NULL,
    price numeric(20,4) NOT NULL CHECK (price > 0),
    kind text NOT NULL CHECK (kind IN ('a', 'b')),
    created_at timestamp with time zone DEFAULT now(),
    PRIMARY KEY (item_id),
    CONSTRAINT item_price_sane CHECK (price < 1000000),
    CHECK (kind <> '')
);

CREATE UNIQUE INDEX item_kind_idx ON shop.item (kind, price);

CREATE OR REPLACE VIEW shop.cheap_item AS SELECT * FROM shop.item WHERE price < 10;

CREATE MATERIALIZED VIEW shop.item_mart AS SELECT kind FROM shop.item;
"""

FUNCTION_SQL = b"""CREATE OR REPLACE FUNCTION shop.total(
    p_item_id text,
    p_currency char(3)
) RETURNS numeric(20,4)
LANGUAGE plpgsql
AS $body$
BEGIN
    CREATE TABLE not_a_declaration (x int);
    INSERT INTO shop.item VALUES ('x');
    RETURN 1;
END;
$body$;

CREATE TABLE shop.after_body (id int);
"""


def index(tmp_path: Path, files: dict[str, bytes], paths: list[str]) -> list[SqlObject]:
    return index_sql(build_repo(tmp_path, files), paths)


def test_schema_table_index_and_views(tmp_path: Path) -> None:
    objects = index(tmp_path, {"sql/001.sql": SCHEMA_SQL}, ["sql/001.sql"])
    assert [(o.kind, o.qualname) for o in objects] == [
        ("schema", "shop"),
        ("table", "shop.item"),
        ("constraint", "shop.item.price_check"),
        ("constraint", "shop.item.kind_check"),
        ("constraint", "shop.item.primary_key"),
        ("constraint", "shop.item.item_price_sane"),
        ("constraint", "shop.item.check_1"),
        ("index", "shop.item_kind_idx"),
        ("view", "shop.cheap_item"),
        ("view", "shop.item_mart"),
    ]


def test_table_signature_is_columns_with_types(tmp_path: Path) -> None:
    table = index(tmp_path, {"sql/001.sql": SCHEMA_SQL}, ["sql/001.sql"])[1]
    assert table.signature == (
        "item_id text, price numeric(20,4), kind text, created_at timestamp with time zone"
    )
    assert table.line == 6


def test_constraint_signatures_keep_the_expression(tmp_path: Path) -> None:
    objects = {o.qualname: o for o in index(tmp_path, {"sql/001.sql": SCHEMA_SQL}, ["sql/001.sql"])}
    assert objects["shop.item.price_check"].signature == "CHECK (price > 0)"
    assert objects["shop.item.primary_key"].signature == "PRIMARY KEY (item_id)"
    assert objects["shop.item.item_price_sane"].signature == "CHECK (price < 1000000)"
    assert objects["shop.item.check_1"].signature == "CHECK (kind <> '')"


def test_index_signature_names_its_table(tmp_path: Path) -> None:
    objects = {o.qualname: o for o in index(tmp_path, {"sql/001.sql": SCHEMA_SQL}, ["sql/001.sql"])}
    assert objects["shop.item_kind_idx"].signature == "ON shop.item (kind, price)"
    assert objects["shop.item_kind_idx"].line == 16


def test_comments_do_not_create_objects_and_do_not_shift_lines(tmp_path: Path) -> None:
    objects = index(tmp_path, {"sql/001.sql": SCHEMA_SQL}, ["sql/001.sql"])
    assert [o.qualname for o in objects if "comment" in o.qualname] == []
    assert [o.line for o in objects if o.kind == "view"] == [18, 20]


def test_function_body_is_not_parsed(tmp_path: Path) -> None:
    objects = index(tmp_path, {"sql/002.sql": FUNCTION_SQL}, ["sql/002.sql"])
    assert [(o.kind, o.qualname) for o in objects] == [
        ("function", "shop.total"),
        ("table", "shop.after_body"),
    ]
    assert objects[0].signature == "(p_item_id text, p_currency char(3)) RETURNS numeric(20,4)"
    assert objects[0].line == 1
    assert objects[1].line == 14


def test_crlf_and_quoted_identifiers(tmp_path: Path) -> None:
    source = b'CREATE SCHEMA "Mixed Case";\r\nCREATE TABLE "Mixed Case"."t" (id int);\r\n'
    objects = index(tmp_path, {"sql/003.sql": source}, ["sql/003.sql"])
    assert [(o.kind, o.qualname, o.line) for o in objects] == [
        ("schema", '"Mixed Case"', 1),
        ("table", '"Mixed Case"."t"', 2),
    ]


def test_unreadable_and_non_sql_paths_are_skipped(tmp_path: Path) -> None:
    files = {"sql/bad.sql": b"\xff\xfe\x00\x01", "notes.md": b"CREATE TABLE x (id int);"}
    assert index(tmp_path, files, ["sql/bad.sql", "notes.md", "sql/absent.sql"]) == []


@needs_meridian
def test_meridian_settlement_schema() -> None:
    objects = index_sql(MERIDIAN, ["sql/060_settlement_schema.sql"])
    by_name = {o.qualname: o for o in objects}
    assert by_name["bank_settlement.daily_settlement"].signature == (
        "tenant_id text, merchant_id text, business_date date, currency char(3),"
        " purchase_amount numeric(20,4), refund_amount numeric(20,4), net_amount numeric(20,4),"
        " event_count bigint"
    )
    assert by_name["bank_settlement.daily_settlement.check_1"].signature == (
        "CHECK (net_amount = purchase_amount - refund_amount)"
    )
    assert by_name["bank_settlement.merchant_event.amount_check"].signature == "CHECK (amount > 0)"
    assert by_name["bank_settlement.merchant_event_close_window"].kind == "index"


@needs_meridian
def test_meridian_refresh_function() -> None:
    objects = index_sql(MERIDIAN, ["sql/061_refresh_daily_settlement.sql"])
    assert [(o.kind, o.qualname, o.line) for o in objects] == [
        ("function", "bank_settlement.refresh_daily_settlement", 1),
    ]
    assert objects[0].signature == (
        "(p_tenant_id text, p_merchant_id text, p_business_date date, p_currency char(3))"
        " RETURNS bank_settlement.daily_settlement"
    )
