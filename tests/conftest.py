import os

# Ensure Settings can load during unit tests without a local .env.
os.environ.setdefault(
    "SECRET_KEY",
    "ci-test-secret-key-please-change-32chars",
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/financeflow",
)
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("MONO_WEBHOOK_SECRET", "whsec_test")
