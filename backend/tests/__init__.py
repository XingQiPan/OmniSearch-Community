"""Test package bootstrap: create the local schema without starting a server."""
from app.core.database import init_db

init_db()
