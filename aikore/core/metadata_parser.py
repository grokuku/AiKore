"""Shared AIKORE-METADATA parsing utilities (lot 3, audit M7).

Historically four divergent parsers existed (crud.py, process_manager x2,
system.py, blueprint_parser.py). They drifted apart and at least one bug came
from ad-hoc post-processing:

    venv_dir_name = os.path.normpath(path).replace('.', '').strip(os.sep)

which strips EVERY dot from the value, turning './my.env' into 'myenv' (the
ignore_patterns() filter then no longer matches and multi-GB venvs get copied).

This module is now the single source of truth for:
  - extracting '# aikore.key = value' entries from a metadata block;
  - un-quoting values ('# aikore.venv_path = "./env"' previously kept the
    literal double quotes);
  - normalizing a venv *path* into a bare directory name WITHOUT destroying
    dots (os.path.basename(os.path.normpath(...)) after validation).

Stdlib only, so the module stays importable in stripped-down unit-test
harnesses.
"""

import os

METADATA_START_MARKER = "### AIKORE-METADATA-START ###"
METADATA_END_MARKER = "### AIKORE-METADATA-END ###"
KEY_PREFIX = "aikore."


def dequote(value: str) -> str:
    """Removes ONE pair of surrounding matching quotes, if present.

    Shell-style metadata values are frequently written quoted:
        # aikore.venv_path = "./env"
    The parsers used to keep the literal quotes, producing paths like
    '"./env"' that never matched anything on disk.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in ("'", '"'):
        return stripped[1:-1]
    return stripped


def iter_metadata_entries(lines):
    """Yields (key, value) tuples from an AIKORE-METADATA block.

    Expected line format inside the block:

        # aikore.some_key = some value

    Lines outside the block are ignored; parsing stops at the END marker.
    Values are returned dequoted (see dequote()).
    """
    in_metadata_block = False
    for raw_line in lines:
        line = raw_line.strip()
        if METADATA_START_MARKER in line:
            in_metadata_block = True
            continue
        if METADATA_END_MARKER in line:
            break
        if not in_metadata_block:
            continue
        if not line.startswith('#') or '=' not in line:
            continue
        parts = line[1:].strip().split('=', 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        if not key.startswith(KEY_PREFIX):
            continue
        key = key[len(KEY_PREFIX):]
        yield key, dequote(parts[1].strip())


def parse_metadata_file(path: str) -> dict:
    """Parses the AIKORE-METADATA block of a file into a dict.

    Returns {} when the file cannot be read (callers keep their previous
    fallback semantics instead of crashing on a missing script).
    """
    metadata = {}
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for key, value in iter_metadata_entries(f):
                metadata[key] = value
    except (IOError, OSError):
        return {}
    return metadata


def normalize_venv_dir_name(venv_path_str: str | None, default: str = "env") -> str:
    """Normalizes a blueprint 'venv_path' value into a bare directory name.

    Fixes audit M7:
      - '"./env"'   -> 'env'     (quotes removed)
      - './my.env'  -> 'my.env'  (dots NO LONGER destroyed; the historical
                      `.replace('.', '')` turned it into 'myenv' and broke
                      ignore_patterns during instance copies)
      - 'venv'      -> 'venv'

    Raises ValueError on absolute paths, '..' segments or NUL bytes so a
    hostile metadata value can never steer copies outside the instance tree.
    """
    if venv_path_str is None:
        return default
    value = dequote(str(venv_path_str)).strip()
    if not value:
        return default

    if "\x00" in value:
        raise ValueError("Invalid venv_path: NUL byte refused.")
    if os.path.isabs(value) or value.startswith("/") or value.startswith("\\"):
        raise ValueError(f"Invalid venv_path '{value}': absolute paths are not allowed.")
    segments = [seg for seg in value.replace("\\", "/").split("/")]
    if ".." in segments:
        raise ValueError(f"Invalid venv_path '{value}': '..' segments are not allowed.")

    normalized = os.path.normpath(value)
    base = os.path.basename(normalized)
    if not base or base in (".", ".."):
        raise ValueError(f"Invalid venv_path '{value}': does not resolve to a directory name.")
    return base


def extract_single(lines_or_path, key: str, default=None):
    """Convenience helper: returns one metadata value (dequoted) or default.

    Accepts either an iterable of lines or a filesystem path string.
    """
    if isinstance(lines_or_path, str):
        entries = parse_metadata_file(lines_or_path)
        return entries.get(key, default)
    for k, v in iter_metadata_entries(lines_or_path):
        if k == key:
            return v
    return default
