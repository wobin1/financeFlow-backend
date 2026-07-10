-- Explicit tax flags for FIRS filing prep (nullable = use category heuristic)
ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS vat_deductible BOOLEAN,
    ADD COLUMN IF NOT EXISTS wht_applicable BOOLEAN,
    ADD COLUMN IF NOT EXISTS wht_rate NUMERIC(5, 2);

CREATE INDEX IF NOT EXISTS idx_transactions_vat_deductible
    ON transactions(user_id, vat_deductible)
    WHERE vat_deductible = true;

CREATE INDEX IF NOT EXISTS idx_transactions_wht_applicable
    ON transactions(user_id, wht_applicable)
    WHERE wht_applicable = true;
