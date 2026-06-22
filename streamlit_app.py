"""Entry point for Streamlit Community Cloud.

The real dashboard lives in ``src/dashboard/app.py`` and uses absolute imports
(``from src...``). Streamlit Cloud runs the main script from the repository root,
so placing this thin launcher at the root puts the repo root on ``sys.path`` and
makes those imports resolve. Importing the module runs the dashboard (its
``main()`` executes at import time).

Locally you can still run either:
    streamlit run streamlit_app.py
    streamlit run src/dashboard/app.py   # with PYTHONPATH=.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.dashboard import app  # noqa: E402,F401  (import runs the dashboard)
