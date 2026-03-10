# Deri V5 Basic Trading Actions

This is a V5 testnet demo for Deri `Pro` mode that mirrors the V4 `deri_v4_basic_trading_actions` flow, but adapts it to the V5 architecture:

- `AddMargin` is an iChain-initiated action signed by the EOA
- `trade` is a dChain-initiated action signed by the smart-account session key
- the EOA-to-smart-account mapping is derived from `(EOA, iChain ChainID)`
- live pool metadata is resolved from Deri's testnet GraphQL endpoint at runtime

Current scope is `Pro` only.

- Pro actions: `AddMargin`, `RemoveMargin`, `trade`
- Lite actions: `AddMarginAndTrade`, `TradeAndRemoveMargin`

Lite is intentionally deferred until after the Pro flow is validated end-to-end.

## Requirements

- Python 3.10+
- `pip install -r requirements.txt`
- a funded EOA on the chosen iChain testnet
- Arbitrum Sepolia ETH for the iChain transaction gas

The dChain trade leg is submitted as a smart-account user operation. The paymaster covers the dChain gas, so the demo does not require separate dChain gas on the wallet.

## Files

- `deri_v5_pro_core/`: shared Deri V5 Pro Python library
- `deri_v5_pro_cli.py`: the main human-facing CLI entrypoint
- `demo.py`: compatibility shim that forwards to `deri_v5_pro_cli.py`
- `abis/`: minimal ABIs for the current V5 flow
- `.env`: local project configuration for secrets and runtime defaults
- `.env.example`: safe template for the local `.env`
- `.session_key.json`: auto-generated local session key for smart-account trading
- `.active_ptoken.json`: local active `pToken` state for the demo
- `.gitignore`: excludes the real `.env` and local runtime state files

## Local `.env`

The demo now auto-loads `deri_v5_basic_trading_actions/.env` before parsing CLI flags.

Recommended setup:

1. keep secrets in the local file `deri_v5_basic_trading_actions/.env`
2. do not put secrets in your shell profile
3. keep `.env` out of git

The checked-in `.env` created here is just a local scaffold with blank secret fields. Fill in:

- `ACCOUNT_ADDRESS`
- `ACCOUNT_PRIVATE`

Keep in `.env` only:

- secrets
- RPC / GraphQL / bundler endpoints
- stable AA infrastructure like `ENTRY_POINT_ADDRESS` and `PAYMASTER_ADDRESS`
- non-trade runtime settings like wait timeout
- optional manual overrides only if you need to force a specific pool while debugging

Do not keep per-trade inputs like symbol, size, or price limit in `.env`.

By default the demo stores the smart-account session key in `deri_v5_basic_trading_actions/.session_key.json`. If you prefer, you can provide `SESSION_KEY_PRIVATE` via `.env` or CLI instead.

The demo also stores the active working `pToken` in `deri_v5_basic_trading_actions/.active_ptoken.json`. That file is local runtime state, not source-controlled config.

By default, the demo auto-selects the pool from the live symbol listing. On current Arbitrum Sepolia testnet, that means BTC/ETH products route to Main Zone and altcoin products route to Inno Zone, but the script derives that from live metadata instead of hardcoding the rule.

If you need to force a pool while debugging, use CLI flags like `--zone` / `--gateway-address`, or set the optional override env vars `ZONE_OVERRIDE`, `GATEWAY_ADDRESS_OVERRIDE`, or `GATEWAY_INDEX_OVERRIDE`.

CLI flags still override the `.env` values if you pass them explicitly.

## Default network

If you do not pass `--ichain-rpc`, the demo uses Arbitrum Sepolia by default and fetches the current live V5 pool metadata for chain `421614`.

## Command surface

The demo is now a small `Pro` trading CLI centered on one active `pToken`.

Core commands:

- `init-p-token`: create the active `pToken` for the demo, or adopt an existing one
- `status`: account, smart-account, session key, balances, pools
- `positions`: positions inside the active `pToken`
- `add-margin`: add margin to the active `pToken`
- `trade`: trade inside the active `pToken`
- `remove-margin`: remove margin from the active `pToken`

Convenience command:

- `close-position`: reads the current position volume and sends the exact opposite `trade`

## Agent Integration

This folder is now set up to be agent-friendly without relying on hidden assumptions:

- [`AGENTS.md`](./AGENTS.md): repo-local operating rules for agents
- [`agent_contract.yaml`](./agent_contract.yaml): machine-readable command, signer, and output contract
- `python deri_v5_pro_cli.py <command> --json`: deterministic structured output for automation

For automated usage, prefer `--json` and parse the response instead of scraping terminal text.

Product model:

- the demo creates or adopts one active `pToken` and then sticks to it
- that active `pToken` is stored locally in `.active_ptoken.json`
- one `pToken` can hold multiple positions, one per symbol
- `add-margin` is the iChain action signed directly by the EOA
- `trade` is the dChain action signed by the session key through the smart account
- `remove-margin` is a dChain smart-account action signed by the EOA owner key
- `close-position` is not a separate protocol primitive; it is just a convenience wrapper over `trade`
- follow-up actions default to the active `pToken` instead of requiring `--p-token-id`

Library model:

- `deri_v5_pro_core` is now the shared implementation surface
- `deri_v5_pro_cli.py` is the main human/debugging CLI entrypoint
- `demo.py` remains as a compatibility shim for older docs and scripts
- other Python applications, including TradeClaw, can import `deri_v5_pro_core` directly instead of shelling out to the CLI

## Typical Pro lifecycle

1. create the active `pToken` with `init-p-token`
2. check setup with `status`
3. trade symbols inside that active `pToken`
4. inspect state with `positions`
5. flatten with `close-position` or another offsetting `trade`
6. withdraw collateral with `remove-margin`

The session-key setup is bootstrap, not the trading primitive itself. In protocol terms:

- iChain / PK-sign: `addMargin`
- dChain / SK-sign: `trade`
- dChain / owner PK-sign via smart account: `removeMargin`

On the first trade, if `SESSION_KEY_PRIVATE` is not set, the demo generates a local session key and stores it in `.session_key.json`.

## Command examples

Check account and smart-account status:

```bash
python deri_v5_pro_cli.py status
```

Create the active `pToken` with margin:

```bash
python deri_v5_pro_cli.py init-p-token \
  --zone main \
  --margin-token USDC \
  --margin-amount 10
```

Create the active `pToken` by auto-selecting the pool from a symbol:

```bash
python deri_v5_pro_cli.py init-p-token \
  --symbol BTCUSD \
  --margin-token USDC \
  --margin-amount 10
```

Adopt an existing `pToken` as the active one:

```bash
python deri_v5_pro_cli.py init-p-token \
  --existing-p-token-id 123456789
```

Add more margin to the active `pToken`:

```bash
python deri_v5_pro_cli.py add-margin \
  --margin-amount 5
```

Trade inside the active `pToken`:

```bash
python deri_v5_pro_cli.py trade \
  --symbol BTCUSD \
  --trade-volume 0.0001
```

Close that position:

```bash
python deri_v5_pro_cli.py close-position \
  --symbol BTCUSD
```

Remove some margin:

```bash
python deri_v5_pro_cli.py remove-margin \
  --margin-amount 5
```

Remove the maximum available margin:

```bash
python deri_v5_pro_cli.py remove-margin \
  --all
```

Inspect positions inside the active `pToken`:

```bash
python deri_v5_pro_cli.py positions
```

If `--price-limit` is omitted for a futures symbol, `trade` and `close-position` derive it from the current dChain index price with `--slippage-pct` (default `5`).

## Pool routing

Some testnet chains have multiple V5 pools.

Current routing rules in the demo:

- after `init-p-token`, `trade`, `close-position`, `add-margin`, `remove-margin`, and `positions` all use the active `pToken` state file
- `init-p-token --existing-p-token-id ...` resolves the pool from that existing `pToken`
- creating a new active `pToken` with `init-p-token` needs either:
  - a manual pool override such as `--zone`, `--gateway-address`, or `--gateway-index`
  - or `--symbol`, which lets the demo auto-select from the live symbol listing
- `status` inspects all live pools on the chain and also shows the current active `pToken`

Manual overrides still work:

```bash
python deri_v5_pro_cli.py ... --zone main
python deri_v5_pro_cli.py ... --zone inno
python deri_v5_pro_cli.py ... --gateway-address 0x49601577be0f0f0a75c38349f38dd85e70accdb7
python deri_v5_pro_cli.py ... --gateway-index 1
```

`main` maps to `Main Zone`, and `inno` maps to `Inno Zone`.

## Notes

- This demo currently implements `Pro` only.
- `requestAddMarginAndTrade` and `requestTradeAndRemoveMargin` belong to `Lite`, not `Pro`.
- The script currently supports the 2-parameter trade path used by futures, options, and power products.
- `remove-margin` submits `engine.executeRemoveMargin(...)` through the smart account, signed by the owner key. The final wallet credit still completes asynchronously on iChain after relayer settlement.
- Gamma symbols are not handled here because V5 gamma trades need 4 trade parameters.
- All live addresses come from `https://testnet-v43dh.deri.io/graphql`.
