# FinanceFlow Backend

Intelligent bookkeeping automation platform for Nigerian businesses, featuring AI-powered transaction categorization, bank integration, and tax filing preparation.

## 🚀 Overview

FinanceFlow is a comprehensive financial management backend tailored for Nigerian businesses. It combines raw SQL performance with AI-powered automation to streamline bookkeeping, transaction categorization, and tax compliance.

### Key Features

- **Raw SQL Performance**: Direct PostgreSQL queries using asyncpg for 2-3x faster performance than ORM
- **AI-Powered Categorization**: Google Gemini integration for intelligent transaction categorization
- **Nigerian Bank Integration**: Mono API integration for seamless bank account connection
- **FIRS Tax Filing Prep**: Automated aggregation of transactions for Nigerian tax compliance
- **Subscription Billing**: Multi-tier pricing with Paystack integration
- **Email Verification**: Zoho Mail integration for secure user onboarding
- **CAC Compliance**: Nigerian business categories compliant with Corporate Affairs Commission requirements

## 📋 Tech Stack

- **Framework**: FastAPI 0.136.0
- **Database**: PostgreSQL with asyncpg (raw SQL, no ORM)
- **AI**: Google Gemini 2.0 Flash
- **Banking**: Mono API (Nigeria)
- **Payments**: Paystack
- **Email**: Zoho Mail REST API
- **SMS**: Twilio / Termii (Nigeria)
- **Testing**: pytest with pytest-asyncio
- **Containerization**: Docker

## 🏗️ Architecture

### File Structure

```
app/
├── main.py                          # FastAPI application entry point
├── core/
│   ├── config.py                    # Configuration and environment variables
│   ├── database.py                  # Database connection and pooling
│   ├── security.py                  # JWT authentication and password hashing
│   ├── logging_utils.py             # Logging and correlation ID middleware
│   ├── plans.py                     # Subscription plan definitions
│   ├── migrations.py                # Database migration runner
│   └── errors.py                    # Error handling
├── services/
│   ├── user_service.py              # User management
│   ├── transaction_service.py       # Transaction operations
│   ├── ai_service.py                # AI categorization (Gemini)
│   ├── mono_service.py              # Mono banking integration
│   ├── firs_service.py              # FIRS tax filing preparation
│   ├── billing_service.py           # Paystack billing
│   ├── email_service.py             # Zoho Mail integration
│   ├── admin_service.py             # Admin operations
│   └── entitlements.py              # Plan entitlements enforcement
└── api/api_v1/
    ├── api.py                       # API router aggregation
    └── endpoints/
        ├── auth.py                  # Authentication endpoints
        ├── users.py                 # User management
        ├── transactions.py          # Transaction CRUD & analytics
        ├── mono.py                  # Mono banking
        ├── firs.py                  # FIRS tax filing
        ├── billing.py               # Billing & subscriptions
        └── admin.py                 # Admin operations

migrations/                          # SQL migration files
tests/                               # Test suite
schema.sql                           # Database schema reference
Dockerfile                           # Docker configuration
requirements.txt                      # Python dependencies
```

### Database Schema

The database uses PostgreSQL with the following key tables:

- **users**: User accounts with business information (CAC number, TIN, business type)
- **transactions**: Financial transactions with AI categorization and tax fields
- **auth_tokens**: Single-use tokens for email verification and password reset

## 🔧 Setup Instructions

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Mono API credentials (for Nigerian bank integration)
- Google Gemini API key
- Paystack account (for billing)
- Zoho Mail account (for email verification)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Database Setup

```bash
# Create database
createdb financeflow

# Run migrations
python -c "from app.core.migrations import run_migrations; run_migrations()"

# Or apply schema directly
psql -d financeflow -f schema.sql
```

### 3. Environment Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required environment variables:

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/financeflow

# Authentication (generate with: python -c "import secrets; print(secrets.token_urlsafe(48))")
SECRET_KEY=your-secret-key-minimum-32-characters

# AI Service
GEMINI_API_KEY=your-gemini-api-key

# Mono Banking (Nigeria)
MONO_SECRET_KEY=your-mono-secret-key
MONO_PUBLIC_KEY=your-mono-public-key
MONO_ENV=test  # or live
USE_MOCK_MONO=true  # Set to false for production

# Paystack Billing
PAYSTACK_SECRET_KEY=your-paystack-secret-key
PAYSTACK_PUBLIC_KEY=your-paystack-public-key

# Email (Zoho Mail)
EMAILS_ENABLED=false  # Set to true for production
ZOHO_CLIENT_ID=your-zoho-client-id
ZOHO_CLIENT_SECRET=your-zoho-client-secret
ZOHO_REFRESH_TOKEN=your-zoho-refresh-token
ZOHO_FROM_ADDRESS=no-reply@yourdomain.com

# Frontend
FRONTEND_URL=http://localhost:3000
```

### 4. Run the Application

```bash
# Development with auto-reload
uvicorn app.main:app --reload

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Using Docker
docker build -t financeflow-backend .
docker run -p 8000:8000 --env-file .env financeflow-backend
```

### 5. Health Check

```bash
curl http://localhost:8000/health
```

## 📡 API Endpoints

### Authentication
- `POST /api/v1/auth/register` - User registration with email verification
- `POST /api/v1/auth/login` - User login with JWT token
- `GET /api/v1/auth/me` - Get current user profile
- `POST /api/v1/auth/verify-email` - Verify email address
- `POST /api/v1/auth/request-password-reset` - Request password reset
- `POST /api/v1/auth/reset-password` - Reset password

### Users
- `GET /api/v1/users/me` - Get user profile
- `PUT /api/v1/users/me` - Update user profile
- `DELETE /api/v1/users/me` - Delete account

### Transactions
- `GET /api/v1/transactions/` - List transactions with filtering and pagination
- `POST /api/v1/transactions/` - Create manual transaction
- `PUT /api/v1/transactions/{id}` - Update transaction
- `DELETE /api/v1/transactions/{id}` - Delete transaction
- `GET /api/v1/transactions/summary/dashboard` - Dashboard summary
- `POST /api/v1/transactions/bulk-update-categories` - Bulk category updates
- `GET /api/v1/transactions/analytics/spending` - Spending analytics

### Mono Banking (Nigeria)
- `POST /api/v1/mono/auth` - Connect Mono account
- `GET /api/v1/mono/account/info` - Get account information
- `POST /api/v1/mono/account/sync` - Sync transactions from bank
- `POST /api/v1/mono/webhook` - Handle Mono webhooks

### FIRS Tax Filing
- `GET /api/v1/firs/summary` - Get tax summary
- `GET /api/v1/firs/export` - Export tax data as CSV
- `GET /api/v1/firs/categories` - Get tax categories

### Billing
- `GET /api/v1/billing/plans` - List available plans
- `POST /api/v1/billing/checkout` - Initialize payment checkout
- `POST /api/v1/billing/webhook` - Handle Paystack webhooks
- `POST /api/v1/billing/cancel` - Cancel subscription

### Admin
- `GET /api/v1/admin/users` - List all users
- `PUT /api/v1/admin/users/{id}/role` - Update user role
- `PUT /api/v1/admin/users/{id}/plan` - Update user plan

## 💳 Subscription Plans

| Plan | Price | Bank Accounts | Transactions | AI Categorization | FIRS Access |
|------|-------|---------------|--------------|-------------------|-------------|
| Free | ₦0 | 0 | 50/month | ❌ | ❌ |
| Starter | ₦3,500/month | 0 | Unlimited | ❌ | ✅ |
| Growth | ₦10,000/month | 2 | Unlimited | ✅ | ✅ |
| Business | ₦20,000/month | 5 | Unlimited | ✅ | ✅ |

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_p2_core.py
```

## 🔒 Security Features

- **JWT Authentication**: Secure token-based authentication
- **Password Hashing**: Argon2 for password storage
- **SQL Injection Prevention**: Parameterized queries only
- **Rate Limiting**: Configurable rate limits per endpoint
- **CORS Protection**: Configurable CORS origins
- **Email Verification**: Required for account activation
- **Single-Use Tokens**: For email verification and password reset

## 🌍 Nigeria-Specific Features

- **CAC Compliance**: Business categories aligned with Corporate Affairs Commission requirements
- **Mono Integration**: Direct connection to Nigerian bank accounts
- **FIRS Preparation**: Automated tax filing preparation for Nigerian businesses
- **Paystack Payments**: Local payment gateway integration
- **NGN Currency**: Default currency set to Nigerian Naira
- **Termii SMS**: Alternative SMS provider for Nigeria

## 📊 Performance

The raw SQL implementation provides:

- **2-3x faster queries** compared to ORM-based implementations
- **Efficient connection pooling** with asyncpg
- **Non-blocking async operations** throughout the stack
- **Optimized indexes** for common query patterns
- **Bulk operations** for efficient data updates

## 🐳 Docker Deployment

```bash
# Build image
docker build -t financeflow-backend .

# Run container
docker run -d \
  --name financeflow \
  -p 8000:8000 \
  --env-file .env \
  financeflow-backend
```

## 📝 Development Notes

### Database Migrations

This project uses SQL migrations instead of Alembic. To create a new migration:

1. Create a new SQL file in `migrations/` with a descriptive name
2. Add your SQL schema changes
3. Run migrations: `python -c "from app.core.migrations import run_migrations; run_migrations()"`

### Raw SQL Guidelines

- Always use parameterized queries with `$1, $2, ...` syntax
- Use `RETURNING *` for INSERT/UPDATE operations to get affected rows
- Leverage PostgreSQL-specific features (JSON, arrays, etc.)
- Create indexes for frequently queried columns
- Use transactions for multi-step operations

### AI Categorization

The AI service uses Google Gemini 2.0 Flash for transaction categorization. Categories are tailored for Nigerian businesses and include:

- Office Supplies
- Professional Services
- Transportation
- Utilities
- Rent/Lease
- Insurance
- Marketing
- Travel
- Equipment
- Meals/Entertainment
- Taxes
- Salaries
- Inventory
- Bank Charges

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Write tests for new functionality
5. Run tests and ensure they pass
6. Submit a pull request

## 📄 License

[Add your license here]

## 📞 Support

For support, email support@financeflow.ng or visit https://financeflow.crimax.ng

## 🔗 Related Links

- [Mono API Documentation](https://docs.withmono.com/)
- [Paystack Documentation](https://paystack.com/docs/)
- [Google Gemini API](https://ai.google.dev/)
- [FIRS TaxPro-Max](https://taxpro.firs.gov.ng/)
