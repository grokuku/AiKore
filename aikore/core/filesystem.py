"""Shared filesystem helpers (lot 3, audit minor #10).

The rmtree error handler used to be duplicated verbatim in
aikore/api/instances.py and aikore/database/crud.py, and swallowed every
exception with a bare print(). This module hosts the single implementation,
logging failures through the `logging` module (ERROR level) so they reach
structured logs instead of disappearing in stdout noise.

Stdlib only, so the module stays importable in stripped-down unit-test
harnesses.
"""

import logging
import os
import stat

logger = logging.getLogger("aikore.filesystem")


def rm_error_handler(func, path, exc):
    """Error handler for shutil.rmtree(..., onexc=...) (Python 3.12+ signature).

    If the failure looks like a read-only permission problem, chmod +u+w and
    retry once. Anything else is logged at ERROR level (with the original
    exception) and swallowed, matching the historical best-effort behaviour —
    but no longer silently: every failure is traceable in the logs.
    """
    try:
        if not os.access(path, os.W_OK):
            os.chmod(path, stat.S_IWUSR)
            func(path)
        else:
            raise exc
    except Exception as e:
        logger.error(
            "Failed to force-delete '%s' during rmtree: %s (%r)",
            path, e, exc,
        )
