"""Shared test setup: isolated temp DB, no live LLM or Maps calls."""
import os
import tempfile

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["LOGISTICS_DB_PATH"] = _db.name
os.environ["LLM_DISABLED"] = "1"
os.environ.pop("GOOGLE_MAPS_API_KEY", None)
