CREATE SCHEMA bank_settlement;

CREATE TABLE bank_settlement.merchant_event (
    tenant_id text NOT NULL,
    event_id text NOT NULL,
    merchant_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    kind text NOT NULL CHECK (kind IN ('purchase', 'refund')),
    status text NOT NULL CHECK (status IN ('settled', 'pending', 'void')),
    currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    amount numeric(20,4) NOT NULL CHECK (amount > 0),
    PRIMARY KEY (tenant_id, event_id)
);

CREATE INDEX merchant_event_close_window
    ON bank_settlement.merchant_event (tenant_id, merchant_id, currency, occurred_at);

CREATE TABLE bank_settlement.daily_settlement (
    tenant_id text NOT NULL,
    merchant_id text NOT NULL,
    business_date date NOT NULL,
    currency char(3) NOT NULL,
    purchase_amount numeric(20,4) NOT NULL,
    refund_amount numeric(20,4) NOT NULL,
    net_amount numeric(20,4) NOT NULL,
    event_count bigint NOT NULL,
    PRIMARY KEY (tenant_id, merchant_id, business_date, currency),
    CHECK (net_amount = purchase_amount - refund_amount)
);

COMMENT ON TABLE bank_settlement.daily_settlement IS
    'Суточное закрытие торговой точки; день задаётся в Europe/Moscow';
