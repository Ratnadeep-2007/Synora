from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import settings

# Configure database engine
connect_args = {}
_db_url = settings.DATABASE_URL
if _db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
elif _db_url.startswith("postgresql://"):
    # Dashboard URLs (Neon/Render) carry the bare scheme, which SQLAlchemy
    # maps to psycopg2. Prefer psycopg3, but fall back to pure-Python
    # pg8000: locked-down Windows hosts block psycopg's binary DLL via
    # Application Control, while Render's Linux build uses psycopg fine.
    try:
        import psycopg  # noqa: F401

        _db_url = "postgresql+psycopg://" + _db_url[len("postgresql://"):]
    except ImportError:
        # pg8000 speaks neither sslmode nor channel_binding query params:
        # fold sslmode=require into an SSL context and drop the rest.
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit("postgresql://" + _db_url[len("postgresql://"):])
        params = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("channel_binding",)]
        query = [(k, v) for k, v in params if k != "sslmode"]
        ssl_required = any(k == "sslmode" and v == "require" for k, v in params)
        if ssl_required:
            import ssl as _ssl

            connect_args["ssl_context"] = _ssl.create_default_context()
        _db_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        _db_url = "postgresql+pg8000://" + _db_url[len("postgresql://"):]

engine = create_engine(
    _db_url,
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
