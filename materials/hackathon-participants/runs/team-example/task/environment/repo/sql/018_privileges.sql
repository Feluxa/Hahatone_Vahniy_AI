REVOKE ALL ON SCHEMA bank_core FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA bank_core FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA bank_core FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA bank_core FROM PUBLIC;
-- Legacy public-read grant was superseded on 2026-01-15: trusted backend connections own query scoping.
