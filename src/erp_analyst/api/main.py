"""uvicorn entry point: `uvicorn erp_analyst.api.main:app`. Kept separate
from app.py so importing app.py (e.g. from tests) never opens a real
Postgres/PostgresSaver connection — only importing this module, or
running it, does.
"""
from erp_analyst.api.app import create_app

app = create_app()
