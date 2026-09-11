CREATE OR REPLACE FUNCTION bank_core.claim_inbound_message(p_tenant_id text,p_message_id text,p_worker text) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE v_claimed boolean;
BEGIN
 UPDATE bank_core.inbound_message SET status='processing' WHERE tenant_id=p_tenant_id AND message_id=p_message_id AND status='received' RETURNING true INTO v_claimed;
 IF COALESCE(v_claimed,false) THEN INSERT INTO bank_core.processing_lock(tenant_id,lock_name,locked_by,expires_at)
 VALUES(p_tenant_id,'message:'||p_message_id,p_worker,clock_timestamp()+interval '5 minutes')
 ON CONFLICT(tenant_id,lock_name) DO UPDATE SET locked_by=EXCLUDED.locked_by,locked_at=clock_timestamp(),expires_at=EXCLUDED.expires_at; END IF;
 RETURN COALESCE(v_claimed,false);
END $$;
CREATE OR REPLACE FUNCTION bank_core.complete_inbound_message(p_tenant_id text,p_message_id text,p_error_code text DEFAULT NULL) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 UPDATE bank_core.inbound_message SET status=CASE WHEN p_error_code IS NULL THEN 'processed' ELSE 'rejected' END,error_code=p_error_code,processed_at=clock_timestamp()
 WHERE tenant_id=p_tenant_id AND message_id=p_message_id AND status='processing';
 DELETE FROM bank_core.processing_lock WHERE tenant_id=p_tenant_id AND lock_name='message:'||p_message_id;
END $$;

