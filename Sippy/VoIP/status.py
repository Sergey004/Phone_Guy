from enum import Enum

__all__ = ["PhoneStatus"]


class PhoneStatus(Enum):
    INACTIVE = 0
    REGISTERING = 1
    REGISTERED = 2
    DEREGISTERING = 3
    FAILED = 4