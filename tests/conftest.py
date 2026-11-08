import os

# Don't create data/default.qto when tests import app.main.
os.environ["TAKEOFF_NO_DEFAULT_APP"] = "1"
os.environ.setdefault("TAKEOFF_CONFIG", os.path.join(os.path.dirname(__file__), ".tmp-config"))
