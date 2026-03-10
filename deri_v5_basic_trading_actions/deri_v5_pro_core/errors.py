from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class DeriV5ProError(RuntimeError):
    """Base error for the Deri V5 Pro Python API."""


@dataclass
class DeriV5ProExecutionError(DeriV5ProError):
    command: str
    message: str
    error_type: str | None = None
    payload: dict[str, Any] | None = None
    captured_logs: list[str] | None = None

    def __str__(self) -> str:
        error_prefix = f"{self.error_type}: " if self.error_type else ""
        return f"{self.command} failed: {error_prefix}{self.message}"


@dataclass
class DeriV5ProContractError(DeriV5ProError):
    command: str
    message: str
    payload: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.command} returned an unsupported contract: {self.message}"
