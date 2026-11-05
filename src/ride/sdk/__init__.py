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

__all__=['ApiError','PeerClient','RideClient','PROTOCOL_VERSION','ControllerAdapter','Journal','UnknownOutcome','PythonControllerAdapter','load_configuration']
