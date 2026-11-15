"""Keep the distributed Colab entry point in sync with the app people test."""

import json
import sys

from scripts.build_notebook import FILES, ROOT, build


def test_notebook_is_current_compilable_and_extracts_exact_sources():
    content = (ROOT / "Solvra_Financial_Triage.ipynb").read_text()
    assert content == build(), "Run python scripts/build_notebook.py after editing the app."
    notebook = json.loads(content)
    cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert len(cells) == 4
    for cell in cells:
        source = "".join(cell["source"])
        if not source.startswith("%pip"):
            compile(source, f"notebook:{cell['id']}", "exec")
    bootstrap = next(cell for cell in cells if "_bundle = " in "".join(cell["source"]))
    namespace = {}
    original_path = sys.path[:]
    try:
        # Execute the repository-generated bootstrap, never user-supplied code.
        exec("".join(bootstrap["source"]), namespace)  # noqa: S102
        extracted = namespace["_solvra_root"]
        for name in FILES:
            assert (extracted / name).read_bytes() == (ROOT / name).read_bytes()
    finally:
        sys.path[:] = original_path
        if "_solvra_runtime" in namespace:
            namespace["_solvra_runtime"].cleanup()
