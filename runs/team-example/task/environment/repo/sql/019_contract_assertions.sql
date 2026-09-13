DO $$
DECLARE v_columns text[];
BEGIN
 SELECT array_agg(column_name ORDER BY ordinal_position) INTO v_columns FROM information_schema.columns
 WHERE table_schema='bank_core' AND table_name='account';
 IF v_columns[1:7]<>ARRAY['tenant_id','account_id','customer_id','currency','status','opened_on','closed_on'] THEN RAISE EXCEPTION 'account contract columns changed'; END IF;
 SELECT array_agg(column_name ORDER BY ordinal_position) INTO v_columns FROM information_schema.columns WHERE table_schema='bank_core' AND table_name='posting';
 IF v_columns[1:10]<>ARRAY['tenant_id','posting_id','account_id','booking_date','value_date','amount','currency','status','reversal_of','source_system'] THEN RAISE EXCEPTION 'posting contract columns changed'; END IF;
END $$;

