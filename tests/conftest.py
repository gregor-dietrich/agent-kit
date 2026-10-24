"""Put the venv's ``bin`` first on PATH.

The hooks the tests start then run under the venv's python3, where coverage
measures them; in a session they run under the user's python3. The floor
tests run each guard once at 3.9 and 3.10, and an import check holds every
hooks/*.py import, function-level ones included, to 3.10's stdlib.
"""

import os
import sys
from pathlib import Path

os.environ["PATH"] = os.pathsep.join(
    [str(Path(sys.executable).parent), *filter(None, [os.environ.get("PATH")])]
)
