-- Distinguish bank-synced vs manually entered bookkeeping records
DO $$ BEGIN
    CREATE TYPE transaction_source AS ENUM ('bank', 'manual');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS source transaction_source NOT NULL DEFAULT 'bank';

-- Existing rows that have no bank external id were likely manual (none yet), keep as bank
UPDATE transactions
SET source = 'bank'
WHERE source IS NULL;

CREATE INDEX IF NOT EXISTS idx_transactions_user_source
    ON transactions(user_id, source);
