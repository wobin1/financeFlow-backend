import uuid
from typing import Union

def ensure_uuid(value: Union[str, uuid.UUID]) -> uuid.UUID:
    """Convert string to UUID or return UUID if already a UUID object"""
    if isinstance(value, uuid.UUID):
        return value
    elif isinstance(value, str):
        return uuid.UUID(value)
    else:
        raise ValueError(f"Cannot convert {type(value)} to UUID")

def uuid_to_str(value: Union[str, uuid.UUID]) -> str:
    """Convert UUID to string or return string if already a string"""
    if isinstance(value, uuid.UUID):
        return str(value)
    elif isinstance(value, str):
        return value
    else:
        raise ValueError(f"Cannot convert {type(value)} to string")
