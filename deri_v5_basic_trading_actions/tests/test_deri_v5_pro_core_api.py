from __future__ import annotations

import unittest
from unittest.mock import patch

from deri_v5_basic_trading_actions.deri_v5_pro_core import DeriV5ProClient, DeriV5ProExecutionError


class DeriV5ProClientTests(unittest.TestCase):
    @patch("deri_v5_basic_trading_actions.deri_v5_pro_core.api.load_local_env")
    @patch("deri_v5_basic_trading_actions.deri_v5_pro_core.api.command_status")
    def test_status_returns_structured_payload(self, status_mock, _load_env_mock) -> None:
        status_mock.return_value = {"portfolio": {"open_positions": 2}}

        client = DeriV5ProClient()
        result = client.status()

        self.assertEqual(result.command, "status")
        self.assertEqual(result.result["portfolio"]["open_positions"], 2)
        self.assertTrue(result.payload["ok"])
        self.assertEqual(result.payload["contract_version"], 1)

    @patch("deri_v5_basic_trading_actions.deri_v5_pro_core.api.load_local_env")
    @patch("deri_v5_basic_trading_actions.deri_v5_pro_core.api.command_add_margin")
    def test_command_exception_becomes_execution_error(self, add_margin_mock, _load_env_mock) -> None:
        add_margin_mock.side_effect = RuntimeError("boom")

        client = DeriV5ProClient()
        with self.assertRaises(DeriV5ProExecutionError) as ctx:
            client.add_margin("1")

        self.assertEqual(ctx.exception.command, "add-margin")
        self.assertEqual(ctx.exception.error_type, "RuntimeError")
        self.assertEqual(ctx.exception.payload["error"]["message"], "boom")


if __name__ == "__main__":
    unittest.main()
