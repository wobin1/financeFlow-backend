-- Billing / subscription fields on users
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS plan VARCHAR(32) NOT NULL DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(32) NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS paystack_customer_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS paystack_subscription_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS paystack_authorization_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS plan_period_end TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS plan_updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_users_plan ON users(plan);
CREATE INDEX IF NOT EXISTS idx_users_subscription_status ON users(subscription_status);

-- Immutable audit log of Paystack / billing events
CREATE TABLE IF NOT EXISTS billing_events (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(64) NOT NULL,
    paystack_reference VARCHAR(128),
    plan VARCHAR(32),
    amount_kobo INTEGER,
    payload JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_events_user_id ON billing_events(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_events_activation_reference
    ON billing_events(paystack_reference)
    WHERE paystack_reference IS NOT NULL AND event_type = 'plan_activated';

CREATE INDEX IF NOT EXISTS idx_billing_events_reference ON billing_events(paystack_reference);
