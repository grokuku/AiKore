import re

from pydantic import BaseModel, field_validator

# --- SECURITY: Shared input-validation patterns (audit lot 2) ---
# NOTE: These constraints are enforced on WRITE paths only (create / rename / copy).
# The read schema (Instance) intentionally inherits NO validator so that legacy DB
# rows (with older, more permissive names) keep loading without errors.

# Instance name: starts with alphanumeric/underscore, 1-64 chars total.
# Inner spaces allowed; refuses '/', '\\', '..', leading dots AND trailing
# spaces: the optional tail must END on a non-space character, so 'abc '
# is rejected while 'abc' and 'a b c' are accepted (lot 2 review L-3b).
INSTANCE_NAME_RE = re.compile(r'[a-zA-Z0-9_](?:[a-zA-Z0-9_\- ]{0,62}[a-zA-Z0-9_\-])?')

# Blueprint filename: same policy as api/system.py::create_custom_blueprint.
BLUEPRINT_FILENAME_RE = re.compile(r'[a-zA-Z0-9_\-]+\.sh')

# Output path: relative folder name (optionally nested), resolved by callers under
# OUTPUTS_DIR.
# NOTE (lot 2 review L-1): the charset alone does NOT prevent traversal — '.' is
# a legal character here, so '..' segments DO match this regex. Traversal is
# actually prevented by the explicit per-segment check in is_valid_output_path()
# below ('..' segments are rejected there), NOT by this charset.
OUTPUT_PATH_RE = re.compile(r'[a-zA-Z0-9_][a-zA-Z0-9_\- ./]{0,254}')


def is_valid_instance_name(value) -> bool:
    """True if value is a safe instance name (no path separators/traversal)."""
    return isinstance(value, str) and bool(INSTANCE_NAME_RE.fullmatch(value))


def is_safe_blueprint_filename(value) -> bool:
    """True if value is a plain '<name>.sh' filename (no traversal possible)."""
    return isinstance(value, str) and bool(BLUEPRINT_FILENAME_RE.fullmatch(value))


def is_valid_output_path(value) -> bool:
    """True if value is a safe relative output folder (never escapes its root)."""
    if not isinstance(value, str) or not OUTPUT_PATH_RE.fullmatch(value):
        return False
    # SECURITY (lot 2 review L-1): the charset allows '.' and therefore '..';
    # THIS per-segment check is what actually prevents traversal:
    return all(segment != '..' for segment in value.split('/'))


# --- Base Schema ---
# Defines the common attributes for an instance, used for creation and reading.
class InstanceBase(BaseModel):
    name: str
    base_blueprint: str
    gpu_ids: str | None = None
    output_path: str | None = None
    autostart: bool = False
    persistent_mode: bool = False
    hostname: str | None = None # NEW: Add hostname field
    use_custom_hostname: bool = False
    
    # --- NEW: Custom Versions ---
    python_version: str | None = None
    cuda_version: str | None = None
    torch_version: str | None = None

# --- Creation Schema ---
# Inherits from Base and is used specifically when creating a new instance via the API.
class InstanceCreate(InstanceBase):
    port: int | None = None
    source_instance_id: int | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not is_valid_instance_name(value):
            raise ValueError(
                "Invalid instance name: 1-64 characters required, must start with a letter, "
                "digit or underscore; only letters, digits, underscores, hyphens and inner "
                "spaces are allowed (no trailing space). Path separators and '..' are forbidden."
            )
        return value

    @field_validator("base_blueprint")
    @classmethod
    def _validate_base_blueprint(cls, value: str) -> str:
        if not is_safe_blueprint_filename(value):
            raise ValueError(
                "Invalid blueprint filename: expected '<name>.sh' containing only "
                "alphanumeric characters, underscores and hyphens."
            )
        return value

    @field_validator("output_path")
    @classmethod
    def _validate_output_path(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_output_path(value):
            raise ValueError(
                "Invalid output path: must be a relative folder name (max 255 chars, "
                "optionally nested) without leading dots, absolute segments or '..'."
            )
        return value

# --- Update Schema ---
# Defines the fields that are allowed to be updated on an existing instance.
class InstanceUpdate(BaseModel):
    name: str | None = None
    base_blueprint: str | None = None
    gpu_ids: str | None = None
    output_path: str | None = None
    autostart: bool | None = None
    persistent_mode: bool | None = None
    hostname: str | None = None
    use_custom_hostname: bool | None = None
    python_version: str | None = None
    cuda_version: str | None = None
    torch_version: str | None = None
    port: int | None = None
    persistent_port: int | None = None
    persistent_display: int | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_instance_name(value):
            raise ValueError(
                "Invalid instance name: 1-64 characters required, must start with a letter, "
                "digit or underscore; only letters, digits, underscores, hyphens and inner "
                "spaces are allowed (no trailing space). Path separators and '..' are forbidden."
            )
        return value

    @field_validator("base_blueprint")
    @classmethod
    def _validate_base_blueprint(cls, value: str | None) -> str | None:
        if value is not None and not is_safe_blueprint_filename(value):
            raise ValueError(
                "Invalid blueprint filename: expected '<name>.sh' containing only "
                "alphanumeric characters, underscores and hyphens."
            )
        return value

    @field_validator("output_path")
    @classmethod
    def _validate_output_path(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_output_path(value):
            raise ValueError(
                "Invalid output path: must be a relative folder name (max 255 chars, "
                "optionally nested) without leading dots, absolute segments or '..'."
            )
        return value

# --- Read Schema ---
# This schema is used when returning instance data from the API.
# It includes attributes that are generated by the database (like `id` and `status`).
class Instance(InstanceBase):
    id: int
    # FIX: Added parent_instance_id so the frontend can group satellites correctly
    parent_instance_id: int | None = None 
    status: str
    pid: int | None = None
    port: int | None = None
    persistent_port: int | None = None
    persistent_display: int | None = None

    class Config:
        # This tells Pydantic to read the data even if it is not a dict,
        # but an ORM model (like our SQLAlchemy model).
        from_attributes = True

class InstanceCopy(BaseModel):
    new_name: str

    @field_validator("new_name")
    @classmethod
    def _validate_new_name(cls, value: str) -> str:
        if not is_valid_instance_name(value):
            raise ValueError(
                "Invalid instance name: 1-64 characters required, must start with a letter, "
                "digit or underscore; only letters, digits, underscores, hyphens and inner "
                "spaces are allowed (no trailing space). Path separators and '..' are forbidden."
            )
        return value

class InstanceInstantiate(BaseModel):
    new_name: str

    @field_validator("new_name")
    @classmethod
    def _validate_new_name(cls, value: str) -> str:
        if not is_valid_instance_name(value):
            raise ValueError(
                "Invalid instance name: 1-64 characters required, must start with a letter, "
                "digit or underscore; only letters, digits, underscores, hyphens and inner "
                "spaces are allowed (no trailing space). Path separators and '..' are forbidden."
            )
        return value