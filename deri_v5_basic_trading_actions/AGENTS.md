# Deri V5 Pro Demo Agent Guide

Read [`agent_contract.yaml`](./agent_contract.yaml) before using [`deri_v5_pro_cli.py`](./deri_v5_pro_cli.py).

## Scope

- This folder is `Pro` only.
- Supported protocol actions: `AddMargin`, `trade`, `RemoveMargin`.
- `Lite` actions are out of scope.

## Terms

- `futures`, `perps`, and `perpetual futures` all mean the `futures` product.
- `options` means `option` only, not `gamma`.
- `power` and `power perps` mean the `power` product.
- `gamma` means `gamma swap` and must be called `gamma` explicitly.

## Source Of Truth

- Agent-facing contract: [`agent_contract.yaml`](./agent_contract.yaml)
- Human overview: [`README.md`](./README.md)
- Executable interface: [`deri_v5_pro_cli.py`](./deri_v5_pro_cli.py)
- Compatibility shim: [`demo.py`](./demo.py)
- Runtime state:
  - local env: `.env`
  - active pToken: `.active_ptoken.json`
  - session key: `.session_key.json`

## Required Agent Behavior

- Prefer `python deri_v5_pro_cli.py <command> --json`.
- Parse the JSON response. Do not scrape human-readable terminal text when `--json` is available.
- Treat `ok=false` JSON responses as authoritative failures.
- Do not infer signer semantics from memory. Use the contract file.
- Do not invent unsupported actions or product categories.

## Operating Model

- The demo centers on one active `pToken`.
- If `.active_ptoken.json` already exists, keep using that `pToken` unless the user explicitly asks to replace it.
- `init-p-token` may create a new `pToken` or adopt an existing one.
- After initialization, `add-margin`, `trade`, `close-position`, `remove-margin`, and `positions` all operate on the active `pToken`.

## Signers

- `init-p-token` create path: EOA-signed on iChain.
- `add-margin`: EOA-signed on iChain.
- `trade`: session-key-signed through the smart account on dChain.
- `close-position`: convenience wrapper over `trade`.
- `remove-margin`: owner private key signs the dChain smart-account user operation.

The user should not need separate dChain ETH. The paymaster covers dChain gas.

## Routing

- Pool selection for new positions should be symbol-driven when possible.
- Manual overrides (`--zone`, `--gateway-address`, `--gateway-index`) are for debugging or explicit operator choice.
- Once the active `pToken` exists, follow-up actions use the gateway saved in `.active_ptoken.json`.

## Product Support

- `futures`: supported, with automatic price-limit discovery.
- `options`: supported, with automatic frontend-style price-limit discovery.
- `power`: supported only when the caller supplies `--price-limit`.
- `gamma`: unsupported in this demo because the protocol call needs 4 trade parameters and this CLI implements the 2-parameter trade path only.

## Safety Rules

- Do not create a replacement active `pToken` unless the user explicitly asks for that.
- Do not call `close-position` a separate protocol primitive; it is an offsetting `trade`.
- Do not assume `BTC/ETH -> Main Zone` forever. The creation path should still respect live symbol listings.
- If a command needs live chain state, prefer the CLI itself over recreating protocol logic elsewhere.
