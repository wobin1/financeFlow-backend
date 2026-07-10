-- FinanceFlow initial database schema

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    phone_number VARCHAR(50),
    plaid_access_token TEXT,
    business_name VARCHAR(255),
    cac_number VARCHAR(50),
    tin_number VARCHAR(50),
    business_type VARCHAR(100),
    country VARCHAR(10) DEFAULT 'NG',
    currency VARCHAR(10) DEFAULT 'NGN',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_users_country ON users(country);

DO $$ BEGIN
    CREATE TYPE transaction_status AS ENUM ('pending', 'confirmed', 'rejected', 'flagged');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plaid_transaction_id VARCHAR(255) UNIQUE,
    merchant_name VARCHAR(255),
    amount NUMERIC(12, 2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'NGN',
    transaction_date DATE NOT NULL,
    raw_description TEXT,
    category VARCHAR(255),
    ai_confidence REAL,
    status transaction_status DEFAULT 'pending',
    vat_deductible BOOLEAN,
    wht_applicable BOOLEAN,
    wht_rate NUMERIC(5, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_transactions_merchant ON transactions(merchant_name);
CREATE INDEX IF NOT EXISTS idx_transactions_plaid_id ON transactions(plaid_transaction_id);
CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_user_status ON transactions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_transactions_user_category ON transactions(user_id, category);

CREATE TABLE IF NOT EXISTS message_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    phone_number VARCHAR(50) NOT NULL,
    message_type VARCHAR(50) NOT NULL,
    direction VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'sent',
    external_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_message_logs_user_id ON message_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_message_logs_phone ON message_logs(phone_number);
CREATE INDEX IF NOT EXISTS idx_message_logs_type ON message_logs(message_type);
CREATE INDEX IF NOT EXISTS idx_message_logs_created ON message_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS bank_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_name VARCHAR(255) NOT NULL,
    account_number VARCHAR(50),
    bank_name VARCHAR(255),
    account_type VARCHAR(50),
    currency VARCHAR(10) DEFAULT 'NGN',
    plaid_account_id VARCHAR(255),
    mono_account_id VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bank_accounts_user_id ON bank_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_bank_accounts_plaid_id ON bank_accounts(plaid_account_id);
CREATE INDEX IF NOT EXISTS idx_bank_accounts_mono_id ON bank_accounts(mono_account_id);

CREATE TABLE IF NOT EXISTS categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category_type VARCHAR(50) NOT NULL,
    country VARCHAR(10) DEFAULT 'NG',
    is_tax_deductible BOOLEAN DEFAULT false,
    parent_category_id UUID REFERENCES categories(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO categories (name, description, category_type, country, is_tax_deductible)
SELECT name, description, category_type, country, is_tax_deductible
FROM (
    VALUES
        ('Sales Revenue', 'Revenue from goods sold', 'income', 'NG', false),
        ('Service Revenue', 'Revenue from services provided', 'income', 'NG', false),
        ('Rental Income', 'Income from property rentals', 'income', 'NG', false),
        ('Interest Income', 'Interest earned on investments', 'income', 'NG', false),
        ('Other Income', 'Other miscellaneous income', 'income', 'NG', false),
        ('Salaries and Wages', 'Employee compensation', 'expense', 'NG', true),
        ('Rent Expense', 'Office and facility rent', 'expense', 'NG', true),
        ('Utilities', 'Electricity, water, internet bills', 'expense', 'NG', true),
        ('Office Supplies', 'Stationery and office materials', 'expense', 'NG', true),
        ('Marketing and Advertising', 'Promotional expenses', 'expense', 'NG', true),
        ('Professional Fees', 'Legal, accounting, consulting fees', 'expense', 'NG', true),
        ('Insurance', 'Business insurance premiums', 'expense', 'NG', true),
        ('Bank Charges', 'Banking fees and charges', 'expense', 'NG', true),
        ('Transport and Logistics', 'Transportation and delivery costs', 'expense', 'NG', true),
        ('Communication', 'Phone, internet, messaging costs', 'expense', 'NG', true),
        ('Repairs and Maintenance', 'Equipment and facility maintenance', 'expense', 'NG', true),
        ('Training and Development', 'Employee training costs', 'expense', 'NG', true),
        ('Travel Expenses', 'Business travel costs', 'expense', 'NG', true),
        ('VAT Payable', 'Value Added Tax (7.5%)', 'liability', 'NG', false),
        ('Withholding Tax', 'Tax withheld at source', 'expense', 'NG', false),
        ('Company Income Tax', 'Corporate income tax', 'expense', 'NG', false),
        ('Personal Income Tax', 'PAYE and personal tax', 'expense', 'NG', false),
        ('Personal', 'Personal non-business expenses', 'expense', 'NG', false)
) AS seed(name, description, category_type, country, is_tax_deductible)
WHERE NOT EXISTS (SELECT 1 FROM categories LIMIT 1);

CREATE INDEX IF NOT EXISTS idx_categories_type ON categories(category_type);
CREATE INDEX IF NOT EXISTS idx_categories_country ON categories(country);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_category_id);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_transactions_updated_at ON transactions;
CREATE TRIGGER update_transactions_updated_at BEFORE UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_message_logs_updated_at ON message_logs;
CREATE TRIGGER update_message_logs_updated_at BEFORE UPDATE ON message_logs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_bank_accounts_updated_at ON bank_accounts;
CREATE TRIGGER update_bank_accounts_updated_at BEFORE UPDATE ON bank_accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE VIEW transaction_summary AS
SELECT
    t.user_id,
    COUNT(*) as total_transactions,
    COUNT(CASE WHEN t.status = 'pending' THEN 1 END) as pending_count,
    COUNT(CASE WHEN t.status = 'confirmed' THEN 1 END) as confirmed_count,
    SUM(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END) as total_income,
    SUM(CASE WHEN t.amount < 0 THEN ABS(t.amount) ELSE 0 END) as total_expenses,
    SUM(t.amount) as net_amount,
    AVG(t.ai_confidence) as avg_confidence
FROM transactions t
GROUP BY t.user_id;

CREATE OR REPLACE VIEW monthly_transaction_summary AS
SELECT
    t.user_id,
    DATE_TRUNC('month', t.transaction_date) as month,
    COUNT(*) as transaction_count,
    SUM(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END) as income,
    SUM(CASE WHEN t.amount < 0 THEN ABS(t.amount) ELSE 0 END) as expenses,
    SUM(t.amount) as net
FROM transactions t
GROUP BY t.user_id, DATE_TRUNC('month', t.transaction_date);

CREATE OR REPLACE VIEW category_breakdown AS
SELECT
    t.user_id,
    t.category,
    COUNT(*) as transaction_count,
    SUM(t.amount) as total_amount,
    AVG(t.amount) as avg_amount,
    AVG(t.ai_confidence) as avg_confidence
FROM transactions t
WHERE t.category IS NOT NULL
GROUP BY t.user_id, t.category;
