import os
import sys
from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Ensure backend directory is in sys.path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

# Set test environment variables before importing app
os.environ["ENVIRONMENT"] = "testing"
os.environ["SECRET_KEY"] = "test-secret-key-1234567890-csrf-signing"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key-for-synesis-credentials"
os.environ["GOOGLE_CLIENT_ID"] = "mock-google-client-id.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "GOCSPX-mock-client-secret-value"
os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:8000/auth/google/callback"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["NVIDIA_API_KEY"] = ""
# Tests exercise the explicitly deterministic knowledge engine. Production
# defaults to NVIDIA NIM; without credentials the engine reports
# 'ai_unavailable' and produces no fabricated output.
os.environ["LLM_PROVIDER"] = "deterministic"

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models.user import User
from app.services.encryption_service import EncryptionService
from app.services.google_oauth import GoogleOAuthService

# In-memory SQLite engine for tests
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Yields a database session with a rollback after test completion."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def test_user(db_session: Session) -> User:
    """Fixture providing a persisted test user."""
    user = User(
        id="usr_test_user_001",
        email="testuser@synesis.internal",
        name="Test User",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(autouse=True)
def ensure_default_test_identities(db_session: Session):
    """Create only the user identities that tests address by fixed IDs.

    No meetings, transcripts, evidence, projects, or state are created —
    each test builds its own records.
    """
    for uid, email, name in [
        ("usr_synesis_default", "default@synesis.internal", "Default User"),
        ("usr_test_lead", "lead-test@synesis.internal", "Test Lead"),
        ("usr_lead", "lead@synesis.internal", "Lead"),
        ("usr_lead_pm", "lead-pm@synesis.internal", "Lead PM"),
        ("usr_lead_architect_carol", "carol@synesis.internal", "Carol"),
    ]:
        existing = db_session.query(User).filter(User.id == uid).first()
        if not existing:
            db_session.add(User(id=uid, email=email, name=name))
    db_session.commit()
    yield


@pytest.fixture
def encryption_service() -> EncryptionService:
    return EncryptionService(settings.ENCRYPTION_KEY)


@pytest.fixture
def google_service(encryption_service: EncryptionService) -> GoogleOAuthService:
    return GoogleOAuthService(settings=settings, encryption_service=encryption_service)


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient that uses the test database session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, base_url="http://localhost:8000") as test_client:
        yield test_client

    app.dependency_overrides.clear()
