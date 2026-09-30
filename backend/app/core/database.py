from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import settings

# Configure database engine
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a database session and ensures it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all database tables and reconcile any legacy prototype schema drift."""
    # Import all models so Base has metadata registered
    import app.models  # noqa: F401
    
    # Check for legacy schema drift in SQLite
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        if "whatsapp_batch_items" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("whatsapp_batch_items")]
            if "batch_id" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("DROP TABLE whatsapp_batch_items"))
    except Exception:
        pass

    Base.metadata.create_all(bind=engine)
