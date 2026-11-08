"""Public, dependency-light SDK. Importing this package has no runtime effects."""
from typing import Protocol
from .adapter import PythonControllerAdapter, load_configuration
from .journal import Journal, UnknownOutcome
from .client import ApiError, PeerClient, RideClient, PROTOCOL_VERSION

class ControllerAdapter(Protocol):
    @staticmethod
    def command(spec: dict) -> str: ...
    @staticmethod
    def probe(spec: dict) -> dict: ...

class ModelServiceAdapter(Protocol):
    """Installed model backend command/probe; no direct Ray lifecycle access."""
    @staticmethod
    def command(spec: dict) -> str: ...
    @staticmethod
    def probe(spec: dict) -> dict: ...

__all__=['ApiError','PeerClient','RideClient','PROTOCOL_VERSION','ControllerAdapter','ModelServiceAdapter','Journal','UnknownOutcome','PythonControllerAdapter','load_configuration']

from .objects import ActionConflict, object_reference, validate_snapshot, validate_action, make_action, verify_action_result
__all__ += ['ActionConflict','object_reference','validate_snapshot','validate_action','make_action','verify_action_result']

from .client import StateClient
__all__ += ['StateClient']
