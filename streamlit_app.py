"""Entry point for Streamlit Community Cloud.

The real dashboard lives in ``src/dashboard/app.py`` and uses absolute imports
(``from src...``). Streamlit Cloud runs the main script from the repository root,
so placing this thin launcher at the root puts the repo root on ``sys.path`` and
makes those imports resolve.

Streamlit re-runs the main script top-to-bottom on every interaction/reload, so
this launcher must re-execute the dashboard each time. ``runpy.run_module`` does
exactly that (it runs the module body afresh, unlike ``import`` which is a no-op
after the first time and would leave reruns blank). ``run_name="__main__"`` makes
app.py's bottom ``main()`` fire, and its top-level ``st.set_page_config`` runs as
the first Streamlit command of every rerun.

Locally you can still run either:
    streamlit run streamlit_app.py
    streamlit run src/dashboard/app.py   # with PYTHONPATH=.
"""

import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

runpy.run_module("src.dashboard.app", run_name="__main__")
