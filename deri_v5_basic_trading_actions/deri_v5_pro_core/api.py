from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from typing import Callable
from typing import Mapping

from .core import (
    JSON_CONTRACT_VERSION,
    LOCAL_ENV_PATH,
    build_common_parser,
    command_add_margin,
    command_init_p_token,
    command_positions,
    command_remove_margin,
    command_status,
    json_value,
    load_local_env,
    run_trade_command,
)
from .errors import DeriV5ProContractError, DeriV5ProExecutionError


@dataclass(frozen=True)
class DeriV5ProCommandSuccess:
    command: str
    result: dict[str, Any]
    payload: dict[str, Any]


def _stringify(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


class DeriV5ProClient:
    """Direct Python interface over the Deri V5 Pro implementation."""

    def __init__(
        self,
        *,
        env_path: str | Path | None = None,
        expected_contract_version: int = JSON_CONTRACT_VERSION,
        common_overrides: Mapping[str, Any] | None = None,
    ) -> None:
        self.env_path = Path(env_path) if env_path is not None else LOCAL_ENV_PATH
        self.expected_contract_version = expected_contract_version
        self.common_overrides = dict(common_overrides or {})

    def status(self) -> DeriV5ProCommandSuccess:
        return self._execute("status", command_status)

    def positions(self, symbol: str | None = None) -> DeriV5ProCommandSuccess:
        return self._execute("positions", command_positions, symbol=symbol)

    def init_p_token(
        self,
        *,
        margin_token: str | None = None,
        margin_amount: Any | None = None,
        symbol: str | None = None,
        category: str = "futures",
        existing_p_token_id: int | None = None,
        replace_active: bool = False,
        zone: str | None = None,
        gateway_address: str | None = None,
        gateway_index: int | None = None,
    ) -> DeriV5ProCommandSuccess:
        if existing_p_token_id is None and (margin_token is None or margin_amount is None):
            raise ValueError("margin_token and margin_amount are required when creating a new pToken")
        return self._execute(
            "init-p-token",
            command_init_p_token,
            margin_token=margin_token,
            margin_amount=_stringify(margin_amount) if margin_amount is not None else None,
            symbol=symbol,
            category=category,
            existing_p_token_id=existing_p_token_id,
            replace_active=replace_active,
            zone=zone,
            gateway_address=gateway_address,
            gateway_index=gateway_index,
        )

    def add_margin(self, margin_amount: Any) -> DeriV5ProCommandSuccess:
        return self._execute("add-margin", command_add_margin, margin_amount=_stringify(margin_amount))

    def trade(
        self,
        *,
        symbol: str,
        trade_volume: Any,
        category: str = "futures",
        price_limit: Any | None = None,
        slippage_pct: Any | None = None,
    ) -> DeriV5ProCommandSuccess:
        return self._execute(
            "trade",
            lambda args: run_trade_command(args, close_position=False),
            symbol=symbol,
            category=category,
            trade_volume=_stringify(trade_volume),
            price_limit=_stringify(price_limit) if price_limit is not None else None,
            slippage_pct=_stringify(slippage_pct) if slippage_pct is not None else "5",
        )

    def close_position(
        self,
        *,
        symbol: str,
        category: str = "futures",
        price_limit: Any | None = None,
        slippage_pct: Any | None = None,
    ) -> DeriV5ProCommandSuccess:
        return self._execute(
            "close-position",
            lambda args: run_trade_command(args, close_position=True),
            symbol=symbol,
            category=category,
            price_limit=_stringify(price_limit) if price_limit is not None else None,
            slippage_pct=_stringify(slippage_pct) if slippage_pct is not None else "5",
        )

    def remove_margin(self, *, margin_amount: Any | None = None, remove_all: bool = False) -> DeriV5ProCommandSuccess:
        if remove_all == (margin_amount is not None):
            raise ValueError("Specify exactly one of margin_amount or remove_all")
        return self._execute(
            "remove-margin",
            command_remove_margin,
            margin_amount=_stringify(margin_amount) if margin_amount is not None else None,
            all=remove_all,
        )

    def _execute(
        self,
        command: str,
        handler: Callable[[argparse.Namespace], dict[str, Any]],
        **overrides: Any,
    ) -> DeriV5ProCommandSuccess:
        load_local_env(self.env_path)
        args = self._build_args(command=command, **overrides)
        captured_stdout = io.StringIO()
        try:
            with redirect_stdout(captured_stdout):
                result = json_value(handler(args))
        except Exception as exc:
            payload = self._error_payload(command, str(exc), exc.__class__.__name__, captured_stdout.getvalue())
            self._validate_contract(command, payload)
            raise DeriV5ProExecutionError(
                command=command,
                message=str(payload["error"]["message"]),
                error_type=str(payload["error"]["type"]),
                payload=payload,
                captured_logs=payload.get("captured_logs"),
            ) from exc

        if not isinstance(result, dict):
            raise DeriV5ProContractError(
                command=command,
                message="success payload is missing a result object",
                payload={"result": result},
            )
        payload = {
            "ok": True,
            "command": command,
            "contract_version": JSON_CONTRACT_VERSION,
            "result": result,
        }
        logs = [line for line in captured_stdout.getvalue().splitlines() if line.strip()]
        if logs:
            payload["captured_logs"] = logs
        self._validate_contract(command, payload)
        return DeriV5ProCommandSuccess(command=command, result=result, payload=payload)

    def _build_args(self, **overrides: Any) -> argparse.Namespace:
        values = {
            **vars(build_common_parser().parse_args([])),
            **self.common_overrides,
            "json_output": False,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def _validate_contract(self, command: str, payload: dict[str, Any]) -> None:
        actual = payload.get("contract_version")
        if actual != self.expected_contract_version:
            raise DeriV5ProContractError(
                command=command,
                message=(
                    f"expected contract version {self.expected_contract_version}, "
                    f"received {actual}"
                ),
                payload=payload,
            )

    @staticmethod
    def _error_payload(command: str, message: str, error_type: str, captured_stdout: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "command": command,
            "contract_version": JSON_CONTRACT_VERSION,
            "error": {
                "type": error_type,
                "message": message,
            },
        }
        logs = [line for line in captured_stdout.splitlines() if line.strip()]
        if logs:
            payload["captured_logs"] = logs
        return payload
