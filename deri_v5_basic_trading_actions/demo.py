#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from eth_account import Account
from eth_keys import keys
from hexbytes import HexBytes
from web3 import Web3
from web3.exceptions import Web3RPCError
from web3.logs import DISCARD

getcontext().prec = 50

ONE_18 = Decimal(10) ** 18
MAX_UINT256 = 2**256 - 1
REMOVE_MARGIN_ALL_SENTINEL = MAX_UINT256 // 10**18
ETH_ADDRESS = "0x0000000000000000000000000000000000000001"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

DEFAULT_GRAPHQL_URL = "https://testnet-v43dh.deri.io/graphql"
DEFAULT_DCHAIN_RPC = "https://testnet-rpc-dchain.deri.io"
DEFAULT_ARBITRUM_SEPOLIA_RPC = "https://sepolia-rollup.arbitrum.io/rpc"
DEFAULT_BUNDLER_RPC = "https://testnet-bundler.deri.io/rpc"
DEFAULT_ENTRY_POINT = "0x4337084d9e255ff0702461cf8895ce9e3b5ff108"
DEFAULT_PAYMASTER = "0x660Db157e1FcDBe1CB15aB5445B7D1C9a8717829"
DEFAULT_SESSION_KEY_VALID_SECONDS = 3 * 24 * 60 * 60
DEFAULT_USER_OP_CALL_GAS_LIMIT = 2_000_000
DEFAULT_USER_OP_VERIFICATION_GAS_LIMIT = 2_000_000
DEFAULT_USER_OP_PRE_VERIFICATION_GAS = 2_000_000
DEFAULT_USER_OP_MAX_FEE_PER_GAS = 410_000_001
DEFAULT_USER_OP_MAX_PRIORITY_FEE_PER_GAS = 4
DEFAULT_USER_OP_PAYMASTER_VERIFICATION_GAS_LIMIT = 1_000_000
DEFAULT_USER_OP_PAYMASTER_POST_OP_GAS_LIMIT = 100_000

ABI_DIR = Path(__file__).resolve().parent / "abis"
LOCAL_ENV_PATH = Path(__file__).resolve().parent / ".env"
LOCAL_SESSION_KEY_PATH = Path(__file__).resolve().parent / ".session_key.json"
LOCAL_ACTIVE_PTOKEN_PATH = Path(__file__).resolve().parent / ".active_ptoken.json"

# Current Arbitrum Sepolia testnet zones exposed by Deri.
MAIN_ZONE_GATEWAY = "0x49601577be0f0f0a75c38349f38dd85e70accdb7"
INNO_ZONE_GATEWAY = "0x55a3c73353c8fe3d2bd8d3509b0c57f1478d6366"

GATEWAY_QUERY = """
query getGateways($chainId:Int){
  gatewayDatas(where:{chainId:$chainId}){
    chainId
    gatewayAddress
    tokenB0
    symbolManager
    engineAddress
    smartAccountFactory
    vault0
    oracle
    swapper
    iou
    lTokenBaseId
    pTokenBaseId
    lTokenIdentifier
    pTokenIdentifier
    relayerFee
    relayer
    minTradeFee
    totalLiquidity
    lpsPnl
    initialMarginRequired
    markets{
      assetAddress
      assetSymbol
      assetDecimals
      vault
      oracleId
      collateralFactor
      price
    }
    symbols{
      symbol
      symbolId
      category
      alpha
      strikePrice
      isCall
      minTradeVolume
    }
  }
}
"""

TD_STATES_QUERY = """
query getTdStates($account:String!, $chainId:Int!){
  tdStates(where:{chainId:$chainId, account:$account}){
    b0Amount
    bAmount
    bToken
    cumulativePnl
    lastCumulativePnlOnEngine
    liquidated
    pTokenId
    singlePosition
    positions{
      cost
      cumulativeFundingPerPowerVolume
      cumulativeFundingPerRealFuturesVolume
      cumulativeFundingPerVolume
      powerVolume
      realFuturesVolume
      symbol
      volume
    }
  }
}
"""

ORACLES_QUERY = """
query getOracles($symbols:String){
  oracles(where:{symbols:$symbols}){
    symbol
    value
    timestamp
  }
}
"""

SYMBOL_STATE_QUERY = """
query getSymbolState($symbolId:String!, $symbolManagerAddress:String!){
  symbolStates(where:{symbolId:$symbolId, symbolManagerAddress:$symbolManagerAddress}){
    symbol
    symbolId
    lastTimestamp
    lastIndexPrice
    lastVolatility
    netVolume
    netCost
    openVolume
    tradersPnl
    initialMarginRequired
    cumulativeFundingPerVolume
    lastNetVolume
    lastNetVolumeBlock
  }
}
"""


@dataclass
class MarketMetadata:
    asset_address: str
    asset_symbol: str
    asset_decimals: int
    vault: str
    oracle_id: str
    collateral_factor: Decimal
    price: Decimal


@dataclass
class SymbolMetadata:
    symbol: str
    symbol_id: str
    category: str
    alpha: Decimal | None
    strike_price: Decimal | None
    is_call: bool
    min_trade_volume: Decimal


@dataclass(frozen=True)
class ZoneConfig:
    key: str
    label: str
    gateway_address: str


@dataclass
class PoolMetadata:
    chain_id: int
    gateway_address: str
    engine_address: str
    smart_account_factory: str
    symbol_manager: str
    token_b0: str
    vault0: str
    oracle: str
    swapper: str
    iou: str
    total_liquidity: Decimal
    lps_pnl: Decimal
    markets: list[MarketMetadata]
    symbols: list[SymbolMetadata]


@dataclass
class SessionKey:
    address: str
    private_key: str
    source: str


@dataclass
class SmartAccountStatus:
    address: str
    deployed: bool
    session_key: str | None
    session_key_valid: bool


@dataclass
class ActivePTokenState:
    account: str
    ichain_chain_id: int
    dchain_chain_id: int
    p_token_id: int
    gateway_address: str
    zone_key: str | None
    margin_token_address: str
    margin_token_symbol: str
    margin_token_decimals: int
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class UserOperationConfig:
    bundler_rpc: str
    entry_point: str
    paymaster: str
    dchain_chain_id: int
    call_gas_limit: int
    verification_gas_limit: int
    pre_verification_gas: int
    max_fee_per_gas: int
    max_priority_fee_per_gas: int
    paymaster_verification_gas_limit: int
    paymaster_post_op_gas_limit: int
    session_key_valid_seconds: int


KNOWN_ZONES_BY_CHAIN = {
    421614: {
        "main": ZoneConfig(
            key="main",
            label="Main Zone",
            gateway_address=MAIN_ZONE_GATEWAY,
        ),
        "inno": ZoneConfig(
            key="inno",
            label="Inno Zone",
            gateway_address=INNO_ZONE_GATEWAY,
        ),
    }
}

ZONE_ALIASES = {
    "main": "main",
    "main-zone": "main",
    "mainzone": "main",
    "inno": "inno",
    "inno-zone": "inno",
    "innozone": "inno",
}


def load_abi(name: str) -> Any:
    path = ABI_DIR / name
    with path.open() as handle:
        return json.load(handle)


def load_local_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def load_active_ptoken_state(path: Path) -> ActivePTokenState | None:
    if not path.exists():
        return None

    payload = json.loads(path.read_text())
    return ActivePTokenState(
        account=payload["account"],
        ichain_chain_id=int(payload["ichainChainId"]),
        dchain_chain_id=int(payload["dchainChainId"]),
        p_token_id=int(payload["pTokenId"]),
        gateway_address=payload["gatewayAddress"],
        zone_key=payload.get("zoneKey"),
        margin_token_address=payload["marginTokenAddress"],
        margin_token_symbol=payload["marginTokenSymbol"],
        margin_token_decimals=int(payload["marginTokenDecimals"]),
        created_at=int(payload["createdAt"]),
        updated_at=int(payload["updatedAt"]),
    )


def save_active_ptoken_state(path: Path, state: ActivePTokenState) -> None:
    path.write_text(
        json.dumps(
            {
                "account": state.account,
                "ichainChainId": state.ichain_chain_id,
                "dchainChainId": state.dchain_chain_id,
                "pTokenId": str(state.p_token_id),
                "gatewayAddress": state.gateway_address,
                "zoneKey": state.zone_key,
                "marginTokenAddress": state.margin_token_address,
                "marginTokenSymbol": state.margin_token_symbol,
                "marginTokenDecimals": state.margin_token_decimals,
                "createdAt": state.created_at,
                "updatedAt": state.updated_at,
            },
            indent=2,
        )
        + "\n"
    )


def require_active_ptoken_state(
    account: str,
    ichain_chain_id: int,
    dchain_chain_id: int,
    path: Path = LOCAL_ACTIVE_PTOKEN_PATH,
) -> ActivePTokenState:
    state = load_active_ptoken_state(path)
    if state is None:
        raise RuntimeError("No active pToken is configured. Run `python demo.py init-p-token ...` first.")

    if state.account.lower() != account.lower():
        raise RuntimeError(
            "The active pToken belongs to a different account. "
            f"active={state.account} current={account}. "
            "Create a new active pToken or switch the configured account."
        )
    if state.ichain_chain_id != ichain_chain_id:
        raise RuntimeError(
            f"The active pToken is configured for iChain {state.ichain_chain_id}, not {ichain_chain_id}."
        )
    if state.dchain_chain_id != dchain_chain_id:
        raise RuntimeError(
            f"The active pToken is configured for dChain {state.dchain_chain_id}, not {dchain_chain_id}."
        )
    return state


def require_connected(web3: Web3, label: str) -> None:
    is_connected = web3.is_connected() if hasattr(web3, "is_connected") else web3.isConnected()
    if not is_connected:
        raise RuntimeError(f"Could not connect to {label}")


def post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc}") from exc


def graphql_request(url: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    data = post_json(url, {"query": query, "variables": variables})
    if data.get("errors"):
        raise RuntimeError(f"GraphQL returned errors: {data['errors']}")
    return data["data"]


def json_rpc_request(url: str, method: str, params: list[Any]) -> Any:
    data = post_json(
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        },
    )
    if data.get("error"):
        raise RuntimeError(f"{method} RPC error: {data['error']}")
    return data.get("result")


def to_checksum(web3: Web3, address: str) -> str:
    return web3.to_checksum_address(address)


def to_decimal(value: str | Decimal | int | float) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def to_token_units(value: str | Decimal, decimals: int) -> int:
    return int(to_decimal(value) * (Decimal(10) ** decimals))


def from_token_units(value: int, decimals: int) -> Decimal:
    return Decimal(value) / (Decimal(10) ** decimals)


def to_18(value: str | Decimal) -> int:
    return int(to_decimal(value) * ONE_18)


def from_18(value: int) -> Decimal:
    return Decimal(value) / ONE_18


def format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def normalize_bytes32(value: Any) -> bytes:
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        data = Web3.to_bytes(hexstr=value)
    else:
        data = bytes(value)
    return data.rjust(32, b"\x00")


def bytes32_is_zero(value: Any) -> bool:
    return normalize_bytes32(value) == b"\x00" * 32


def bytes32_to_signed_int(value: Any) -> int:
    raw = int.from_bytes(normalize_bytes32(value), "big", signed=False)
    if raw >= 1 << 255:
        raw -= 1 << 256
    return raw


def bytes32_to_address(value: Any) -> str | None:
    raw = normalize_bytes32(value)
    if raw == b"\x00" * 32:
        return None
    return Web3.to_checksum_address(raw[-20:].hex())


def normalize_zone_key(zone: str | None) -> str | None:
    if not zone:
        return None
    normalized = zone.strip().lower().replace("_", "-").replace(" ", "-")
    return ZONE_ALIASES.get(normalized, normalized)


def get_known_zone(chain_id: int, zone_key: str) -> ZoneConfig:
    chain_zones = KNOWN_ZONES_BY_CHAIN.get(chain_id, {})
    zone = chain_zones.get(zone_key)
    if zone:
        return zone

    available = ", ".join(config.label for config in chain_zones.values()) or "none"
    raise RuntimeError(
        f"--zone {zone_key} is not configured for chain {chain_id}. Known zones: {available}"
    )


def infer_known_zone(chain_id: int, gateway_address: str) -> ZoneConfig | None:
    normalized = gateway_address.lower()
    for zone in KNOWN_ZONES_BY_CHAIN.get(chain_id, {}).values():
        if zone.gateway_address.lower() == normalized:
            return zone
    return None


def parse_pool_metadata(row: dict[str, Any]) -> PoolMetadata:
    markets = [
        MarketMetadata(
            asset_address=market["assetAddress"],
            asset_symbol=market["assetSymbol"],
            asset_decimals=int(market["assetDecimals"]),
            vault=market["vault"],
            oracle_id=market["oracleId"],
            collateral_factor=to_decimal(market["collateralFactor"]),
            price=to_decimal(market["price"]),
        )
        for market in row["markets"]
    ]
    symbols = [
        SymbolMetadata(
            symbol=symbol["symbol"],
            symbol_id=symbol["symbolId"],
            category=symbol["category"],
            alpha=to_decimal(symbol["alpha"]) if symbol.get("alpha") not in {None, ""} else None,
            strike_price=to_decimal(symbol["strikePrice"]) if symbol.get("strikePrice") not in {None, ""} else None,
            is_call=bool(symbol.get("isCall")),
            min_trade_volume=to_decimal(symbol["minTradeVolume"]),
        )
        for symbol in row["symbols"]
    ]

    return PoolMetadata(
        chain_id=int(row["chainId"]),
        gateway_address=row["gatewayAddress"],
        engine_address=row["engineAddress"],
        smart_account_factory=row["smartAccountFactory"],
        symbol_manager=row["symbolManager"],
        token_b0=row["tokenB0"],
        vault0=row["vault0"],
        oracle=row["oracle"],
        swapper=row["swapper"],
        iou=row["iou"],
        total_liquidity=to_decimal(row["totalLiquidity"]),
        lps_pnl=to_decimal(row["lpsPnl"]),
        markets=markets,
        symbols=symbols,
    )


def fetch_pool_metadatas(graph_url: str, chain_id: int) -> list[PoolMetadata]:
    rows = graphql_request(graph_url, GATEWAY_QUERY, {"chainId": chain_id})["gatewayDatas"]
    if not rows:
        raise RuntimeError(f"No gateway data found for chain_id={chain_id}")
    return [parse_pool_metadata(row) for row in rows]


def fetch_td_states(graph_url: str, chain_id: int, account: str) -> list[dict[str, Any]]:
    return graphql_request(
        graph_url,
        TD_STATES_QUERY,
        {"chainId": chain_id, "account": account},
    )["tdStates"]


def fetch_oracles(graph_url: str, symbols: list[str]) -> dict[str, dict[str, Any]]:
    query_symbols = ",".join(dict.fromkeys(symbols))
    rows = graphql_request(graph_url, ORACLES_QUERY, {"symbols": query_symbols})["oracles"]
    return {row["symbol"]: row for row in rows}


def fetch_symbol_state(graph_url: str, symbol_manager_address: str, symbol_id: str) -> dict[str, Any] | None:
    rows = graphql_request(
        graph_url,
        SYMBOL_STATE_QUERY,
        {"symbolId": symbol_id, "symbolManagerAddress": symbol_manager_address},
    )["symbolStates"]
    return rows[0] if rows else None


def decimal_or_zero(value: Any) -> Decimal:
    if value in {None, "", "0x", "0X"}:
        return Decimal("0")
    return to_decimal(value)


def find_pool_by_gateway(pools: list[PoolMetadata], gateway_address: str) -> PoolMetadata:
    normalized = gateway_address.lower()
    for pool in pools:
        if pool.gateway_address.lower() == normalized:
            return pool
    raise RuntimeError(f"gateway_address={gateway_address} was not returned by the live metadata query")


def select_pool_without_symbol(
    pools: list[PoolMetadata],
    chain_id: int,
    gateway_address: str | None,
    gateway_index: int | None,
    zone: str | None,
) -> tuple[PoolMetadata, ZoneConfig | None, str]:
    explicit_gateway = gateway_address.strip() if gateway_address else None
    normalized_zone = normalize_zone_key(zone)

    if explicit_gateway:
        pool = find_pool_by_gateway(pools, explicit_gateway)
        return pool, infer_known_zone(chain_id, pool.gateway_address), "gateway-address override"

    if normalized_zone:
        zone_config = get_known_zone(chain_id, normalized_zone)
        pool = find_pool_by_gateway(pools, zone_config.gateway_address)
        return pool, zone_config, "zone override"

    if gateway_index is not None:
        if gateway_index < 0 or gateway_index >= len(pools):
            raise RuntimeError(
                f"gateway_index={gateway_index} is out of range for {len(pools)} pools on chain {chain_id}"
            )
        pool = pools[gateway_index]
        return pool, infer_known_zone(chain_id, pool.gateway_address), "gateway-index override"

    if len(pools) == 1:
        pool = pools[0]
        return pool, infer_known_zone(chain_id, pool.gateway_address), "single available pool"

    descriptions = []
    for pool in pools:
        zone_config = infer_known_zone(chain_id, pool.gateway_address)
        if zone_config:
            descriptions.append(f"{zone_config.label} ({pool.gateway_address})")
        else:
            descriptions.append(pool.gateway_address)
    raise RuntimeError(
        "Pool selection is ambiguous. Pass --zone, --gateway-address, --gateway-index, or --symbol. "
        + "Available pools: "
        + ", ".join(descriptions)
    )


def resolve_pool_from_active_state(
    pools: list[PoolMetadata],
    active_state: ActivePTokenState,
) -> tuple[PoolMetadata, ZoneConfig | None, str]:
    pool = find_pool_by_gateway(pools, active_state.gateway_address)
    zone = infer_known_zone(active_state.ichain_chain_id, pool.gateway_address)
    return pool, zone, "active pToken state"


def find_market_by_address(pool: PoolMetadata, asset_address: str) -> MarketMetadata:
    normalized = asset_address.lower()
    for market in pool.markets:
        if market.asset_address.lower() == normalized:
            return market
    raise RuntimeError(f"Margin token {asset_address} is not enabled on gateway {pool.gateway_address}")


def find_td_state_row(td_states: list[dict[str, Any]], p_token_id: int) -> dict[str, Any] | None:
    target = str(p_token_id)
    for td_state in td_states:
        if str(td_state.get("pTokenId")) == target:
            return td_state
    return None


def find_market(pool: PoolMetadata, token_hint: str) -> MarketMetadata:
    hint = token_hint.strip()
    if hint.lower() == "tokenb0":
        for market in pool.markets:
            if market.asset_address.lower() == pool.token_b0.lower():
                return market
        raise RuntimeError("tokenB0 is not present in pool.markets")

    if Web3.is_address(hint):
        normalized = hint.lower()
        for market in pool.markets:
            if market.asset_address.lower() == normalized:
                return market
        raise RuntimeError(f"Margin market {hint} is not enabled on gateway {pool.gateway_address}")

    normalized = hint.upper()
    for market in pool.markets:
        if market.asset_symbol.upper() == normalized:
            return market
    available = ", ".join(sorted(market.asset_symbol for market in pool.markets))
    raise RuntimeError(f"Unknown margin token {token_hint}. Available markets: {available}")


def find_symbol_matches(pool: PoolMetadata, symbol_name: str, category: str | None) -> list[SymbolMetadata]:
    normalized_symbol = symbol_name.upper()
    normalized_category = category.lower() if category else None
    return [
        symbol
        for symbol in pool.symbols
        if symbol.symbol.upper() == normalized_symbol
        and (normalized_category is None or symbol.category.lower() == normalized_category)
    ]


def find_symbol(pool: PoolMetadata, symbol_name: str, category: str | None) -> SymbolMetadata:
    matches = find_symbol_matches(pool, symbol_name, category)
    if not matches:
        raise RuntimeError(
            f"Could not find symbol={symbol_name}"
            + (f" category={category}" if category else "")
            + f" on gateway {pool.gateway_address}"
        )
    if len(matches) > 1:
        categories = ", ".join(symbol.category for symbol in matches)
        raise RuntimeError(
            f"symbol={symbol_name} matched multiple categories ({categories}). "
            "Pass --category to disambiguate."
        )
    return matches[0]


def select_pool_and_symbol(
    pools: list[PoolMetadata],
    chain_id: int,
    symbol_name: str,
    category: str | None,
    gateway_address: str | None,
    gateway_index: int | None,
    zone: str | None,
) -> tuple[PoolMetadata, SymbolMetadata, ZoneConfig | None, str]:
    explicit_gateway = gateway_address.strip() if gateway_address else None
    normalized_zone = normalize_zone_key(zone)

    if explicit_gateway:
        pool = find_pool_by_gateway(pools, explicit_gateway)
        zone_config = infer_known_zone(chain_id, pool.gateway_address)
        if normalized_zone:
            requested_zone = get_known_zone(chain_id, normalized_zone)
            if requested_zone.gateway_address.lower() != pool.gateway_address.lower():
                raise RuntimeError(
                    "--zone and --gateway-address point to different pools. "
                    f"{requested_zone.label} uses {requested_zone.gateway_address}."
                )
            zone_config = requested_zone
        return pool, find_symbol(pool, symbol_name, category), zone_config, "gateway-address override"

    if normalized_zone:
        zone_config = get_known_zone(chain_id, normalized_zone)
        pool = find_pool_by_gateway(pools, zone_config.gateway_address)
        return pool, find_symbol(pool, symbol_name, category), zone_config, "zone override"

    if gateway_index is not None:
        if gateway_index < 0 or gateway_index >= len(pools):
            raise RuntimeError(
                f"gateway_index={gateway_index} is out of range for {len(pools)} pools on chain {chain_id}"
            )
        pool = pools[gateway_index]
        return (
            pool,
            find_symbol(pool, symbol_name, category),
            infer_known_zone(chain_id, pool.gateway_address),
            "gateway-index override",
        )

    candidates: list[tuple[PoolMetadata, SymbolMetadata]] = []
    for pool in pools:
        matches = find_symbol_matches(pool, symbol_name, category)
        if len(matches) > 1:
            categories = ", ".join(symbol.category for symbol in matches)
            raise RuntimeError(
                f"symbol={symbol_name} matched multiple categories ({categories}) "
                f"on gateway {pool.gateway_address}. Pass --category to disambiguate."
            )
        if matches:
            candidates.append((pool, matches[0]))

    if not candidates:
        available_gateways = ", ".join(pool.gateway_address for pool in pools)
        raise RuntimeError(
            f"Could not find symbol={symbol_name}"
            + (f" category={category}" if category else "")
            + f" on any gateway for chain {chain_id}. Gateways checked: {available_gateways}"
        )

    if len(candidates) > 1:
        descriptions = []
        for pool, _symbol in candidates:
            zone_config = infer_known_zone(chain_id, pool.gateway_address)
            if zone_config:
                descriptions.append(f"{zone_config.label} ({pool.gateway_address})")
            else:
                descriptions.append(pool.gateway_address)
        raise RuntimeError(
            f"symbol={symbol_name}"
            + (f" category={category}" if category else "")
            + " is available on multiple pools: "
            + ", ".join(descriptions)
            + ". Pass --zone or --gateway-address to disambiguate."
        )

    pool, symbol = candidates[0]
    return pool, symbol, infer_known_zone(chain_id, pool.gateway_address), "auto-selected from live symbol listing"


def get_td_state(engine_contract, p_token_id: int):
    return engine_contract.functions.getTdState(p_token_id).call()


def resolve_pool_by_p_token_id(
    pools: list[PoolMetadata],
    dchain_web3: Web3,
    p_token_id: int,
    expected_account: str | None = None,
) -> tuple[PoolMetadata, Any, ZoneConfig | None, str]:
    matches: list[tuple[PoolMetadata, Any]] = []
    for pool in pools:
        engine = get_contract(dchain_web3, pool.engine_address, "EngineImplementation.json")
        state = get_td_state(engine, p_token_id)
        td_account = bytes32_to_address(state[1])
        if td_account:
            matches.append((pool, state))

    if not matches:
        raise RuntimeError(f"pTokenId={p_token_id} was not found on any live pool for chain {dchain_web3.eth.chain_id}")

    if len(matches) > 1:
        raise RuntimeError(f"pTokenId={p_token_id} matched multiple pools, which should not happen")

    pool, state = matches[0]
    td_account = bytes32_to_address(state[1])
    if expected_account and td_account and td_account.lower() != expected_account.lower():
        print(
            "Warning:",
            f"tdState.account={td_account} does not match the requested account {expected_account}",
        )
    return pool, state, infer_known_zone(pool.chain_id, pool.gateway_address), "resolved from existing pTokenId"


def get_contract(web3: Web3, address: str, abi_name: str):
    return web3.eth.contract(address=to_checksum(web3, address), abi=load_abi(abi_name))


def prepare_transaction(function_call, web3: Web3, account: str, value: int = 0) -> dict[str, Any]:
    latest_block = web3.eth.get_block("latest")
    tx = {
        "from": to_checksum(web3, account),
        "nonce": web3.eth.get_transaction_count(to_checksum(web3, account)),
        "chainId": web3.eth.chain_id,
        "value": value,
    }
    base_fee = latest_block.get("baseFeePerGas")
    if base_fee is not None:
        try:
            priority_fee = int(web3.eth.max_priority_fee)
        except Exception:
            priority_fee = 1_000_000
        tx["maxPriorityFeePerGas"] = max(priority_fee, 1_000_000)
        tx["maxFeePerGas"] = max(int(base_fee) * 2 + tx["maxPriorityFeePerGas"], tx["maxPriorityFeePerGas"])
    else:
        tx["gasPrice"] = web3.eth.gas_price
    estimated = function_call.estimate_gas(tx)
    tx["gas"] = int(estimated * 1.2) + 25_000
    return function_call.build_transaction(tx)


def send_built_transaction(transaction: dict[str, Any], web3: Web3, private_key: str):
    for _attempt in range(2):
        signed = web3.eth.account.sign_transaction(transaction, private_key)
        raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        try:
            tx_hash = web3.eth.send_raw_transaction(raw_tx)
        except Web3RPCError as exc:
            if "max fee per gas less than block base fee" in str(exc) and "maxFeePerGas" in transaction:
                latest_block = web3.eth.get_block("latest")
                base_fee = int(latest_block.get("baseFeePerGas") or 0)
                priority_fee = int(transaction.get("maxPriorityFeePerGas", 1_000_000))
                transaction["maxFeePerGas"] = max(
                    base_fee * 2 + priority_fee,
                    int(transaction["maxFeePerGas"]) * 2,
                )
                continue
            raise

        receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError(f"Transaction reverted: {tx_hash.hex()}")
        return receipt

    raise RuntimeError("Failed to submit the transaction after refreshing the fee cap")


def send_transaction(function_call, web3: Web3, account: str, private_key: str, value: int = 0):
    transaction = prepare_transaction(function_call, web3, account, value=value)
    return send_built_transaction(transaction, web3, private_key)


def approve_if_needed(
    token_contract,
    owner: str,
    spender: str,
    amount: int,
    web3: Web3,
    private_key: str,
) -> None:
    current = token_contract.functions.allowance(
        to_checksum(web3, owner),
        to_checksum(web3, spender),
    ).call()
    if current >= amount:
        print(f"Approval already set for {spender}")
        return
    print(f"Approving {spender} to spend the margin token")
    receipt = send_transaction(
        token_contract.functions.approve(to_checksum(web3, spender), MAX_UINT256),
        web3,
        owner,
        private_key,
    )
    print(f"approve tx: {receipt.transactionHash.hex()}")


def extract_dtoken_id(event_args: Any) -> int:
    info = event_args["dTokenInfo"]
    if isinstance(info, (list, tuple)):
        return int(info[2])
    return int(info["dTokenId"])


def request_add_margin(
    gateway_contract,
    market: MarketMetadata,
    amount: Decimal,
    web3: Web3,
    account: str,
    private_key: str,
    p_token_id: int = 0,
) -> tuple[Any, int, str]:
    amount_units = to_token_units(amount, market.asset_decimals)
    tx_value = amount_units if market.asset_address.lower() == ETH_ADDRESS.lower() else 0
    last_error: Exception | None = None
    candidates = [
        (
            "requestAddMargin(uint256,address,uint256,bool)",
            [p_token_id, to_checksum(web3, market.asset_address), amount_units, False],
        ),
        (
            "requestAddMargin(uint256,address,uint256)",
            [p_token_id, to_checksum(web3, market.asset_address), amount_units],
        ),
    ]

    for signature, params in candidates:
        try:
            function_call = gateway_contract.get_function_by_signature(signature)(*params)
            transaction = prepare_transaction(function_call, web3, account, value=tx_value)
        except Exception as exc:
            last_error = exc
            continue

        receipt = send_built_transaction(transaction, web3, private_key)
        events = gateway_contract.events.RequestAddMargin().process_receipt(receipt, errors=DISCARD)
        if not events:
            raise RuntimeError("RequestAddMargin event not found in receipt")
        return receipt, extract_dtoken_id(events[0]["args"]), signature

    raise RuntimeError(f"Could not build requestAddMargin transaction: {last_error}") from last_error


def wait_for_td_state(engine_contract, p_token_id: int, timeout: int, poll_interval: float):
    print(f"Waiting for dChain trader state for pTokenId={p_token_id}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = engine_contract.functions.getTdState(p_token_id).call()
        account = state[1]
        if not bytes32_is_zero(account):
            return state
        time.sleep(poll_interval)
    raise TimeoutError("Timed out waiting for dChain trader state to be created")


def encode_contract_call(contract, fn_name: str, args: list[Any]) -> str:
    if hasattr(contract, "encode_abi"):
        return contract.encode_abi(fn_name, args=args)
    if hasattr(contract, "encodeABI"):
        return contract.encodeABI(fn_name=fn_name, args=args)
    return getattr(contract.functions, fn_name)(*args)._encode_transaction_data()


def get_position(symbol_manager_contract, symbol: SymbolMetadata, p_token_id: int) -> dict[str, int]:
    raw = symbol_manager_contract.functions.getPosition(symbol.symbol_id, p_token_id).call()
    return {
        "volume_18": bytes32_to_signed_int(raw[0]),
        "cost_18": bytes32_to_signed_int(raw[1]),
        "cumulative_funding_per_volume_18": bytes32_to_signed_int(raw[2]),
    }


def wait_for_position_change(
    symbol_manager_contract,
    symbol: SymbolMetadata,
    p_token_id: int,
    initial_volume_18: int,
    expected_delta_18: int | None,
    timeout: int,
    poll_interval: float,
) -> dict[str, int]:
    print(f"Waiting for {symbol.symbol} position on pTokenId={p_token_id}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        position = get_position(symbol_manager_contract, symbol, p_token_id)
        volume = position["volume_18"]
        if expected_delta_18 is None and volume != initial_volume_18:
            return position
        if expected_delta_18 is not None and volume == initial_volume_18 + expected_delta_18:
            return position
        time.sleep(poll_interval)
    raise TimeoutError("Timed out waiting for the position update on dChain")


def calculate_mark_price(index_price: float, k: float, traders_net_volume: float) -> float:
    return index_price * (k * traders_net_volume + 1)


def calculate_cost(index_price: float, k: float, traders_net_volume: float, trade_volume: float) -> float:
    return index_price * ((((traders_net_volume + trade_volume) ** 2) - (traders_net_volume**2)) * k / 2 + trade_volume)


def calculate_everlasting_option(
    index_price: float,
    strike_price: float,
    volatility: float,
    is_call: bool,
) -> tuple[float, float, float, float, float, float]:
    risk_free_rate = 0.1095
    time_horizon = 7 / 365
    one_plus_rt = 1 + risk_free_rate * time_horizon

    p = 1 + 2 * risk_free_rate / (volatility**2)
    q = 1 - 2 * risk_free_rate / (volatility**2)
    u = math.sqrt(p**2 + 8 / (volatility**2) / time_horizon) / p
    w = math.sqrt(q**2 + 8 * one_plus_rt / (volatility**2) / time_horizon) / (-q)

    if index_price >= strike_price:
        a = (index_price / strike_price) ** (-(1 + u) * p / 2) * ((1 / u) - 1) / 2
        b = (index_price / strike_price) ** ((1 + w) * q / 2) * ((1 / w) - 1) / 2 / one_plus_rt
        d_v_d_s = a * (1 - ((1 + u) * p / 2)) - b * (strike_price / index_price * ((1 + w) * q / 2))
        s_a_k_b = index_price * a - strike_price * b
        if is_call:
            theoretical_value = s_a_k_b + (index_price - strike_price / one_plus_rt)
            intrinsic_value = (index_price - strike_price) / one_plus_rt
            delta = d_v_d_s + 1
        else:
            theoretical_value = s_a_k_b
            intrinsic_value = 0.0
            delta = d_v_d_s
        t1 = (1 + u) * p / 2
        t2 = (1 + w) * q / 2
        gamma = a / index_price * (t1 - 1) * t1 - b * strike_price / index_price * (t2 - 1) / index_price * t2
    else:
        a = (index_price / strike_price) ** (-(1 - u) * p / 2) * ((1 / u) + 1) / 2
        b = (index_price / strike_price) ** ((1 - w) * q / 2) * ((1 / w) + 1) / 2 / one_plus_rt
        d_v_d_s = a * (1 - ((1 - u) * p / 2)) - b * (strike_price / index_price * ((1 - w) * q / 2))
        s_a_k_b = index_price * a - strike_price * b
        if is_call:
            theoretical_value = s_a_k_b
            intrinsic_value = 0.0
            delta = d_v_d_s
        else:
            theoretical_value = s_a_k_b - (index_price - strike_price / one_plus_rt)
            intrinsic_value = (strike_price - index_price) / one_plus_rt
            delta = d_v_d_s - 1
        t1 = (1 - u) * p / 2
        t2 = (1 - w) * q / 2
        gamma = a * (t1 - 1) / index_price * t1 - b * strike_price / index_price * (t2 - 1) / index_price * t2

    time_value = theoretical_value - intrinsic_value
    old_u = math.sqrt(8 / (volatility * volatility) / time_horizon + 1)
    return theoretical_value, intrinsic_value, delta, gamma, time_value, old_u


def calculate_option_k(
    index_price: float,
    theoretical_price: float,
    alpha: float,
    delta: float,
    liquidity: float,
    lps_pnl: float,
) -> float:
    if theoretical_price == 0:
        return 0.0
    return (index_price**2 / theoretical_price) * abs(delta) * alpha / (liquidity + lps_pnl)


def calculate_vega(price: float, strike: float, u: float, dvol: float, time_value: float) -> float:
    if price > strike:
        seg1 = (u / 2) * math.log(price / strike) + 1
    else:
        seg1 = 1 - (u / 2) * math.log(price / strike)
    seg2 = 1 - (1 / (u**2))
    seg3 = time_value / dvol
    return seg1 * seg2 * seg3


def calculate_price_limit(
    theoretical_price: float,
    k: float,
    volume: float,
    net_volume: float,
    slippage: float,
    mark_price: float,
    price: float,
    strike: float | None = None,
    time_value_delta_u: tuple[float, float, float] | None = None,
    volatility: float | None = None,
) -> float:
    if volume == 0:
        return 0.0

    cost = calculate_cost(theoretical_price, k, net_volume, volume)
    trade_price = cost / volume
    vega = None
    if time_value_delta_u is not None:
        if strike is None or volatility is None:
            raise RuntimeError("strike and volatility are required when time_value_delta_u is provided")
        vega = calculate_vega(price, strike, time_value_delta_u[2], volatility, time_value_delta_u[0])

    if volume > 0:
        price_limit = trade_price + slippage * mark_price
    else:
        price_limit = trade_price - slippage * mark_price

    if vega is not None:
        if volume > 0:
            price_limit += vega * 0.005
        else:
            price_limit -= vega * 0.005

    return price_limit


def get_option_query_price_symbol(symbol: SymbolMetadata) -> str:
    return symbol.symbol.split("-")[0]


def get_futures_index_price(symbol_manager_contract, symbol: SymbolMetadata) -> Decimal:
    if symbol.category.lower() != "futures":
        raise RuntimeError("Automatic price-limit discovery only supports futures symbols")
    state = symbol_manager_contract.functions.getState(symbol.symbol_id).call()
    last_index_price_18 = bytes32_to_signed_int(state[10])
    if last_index_price_18 <= 0:
        raise RuntimeError(f"Invalid lastIndexPrice for {symbol.symbol}: {last_index_price_18}")
    return from_18(last_index_price_18)


def auto_price_limit(
    graph_url: str,
    symbol_manager_contract,
    pool: PoolMetadata,
    symbol: SymbolMetadata,
    trade_volume_18: int,
    slippage_pct: Decimal,
) -> Decimal:
    if symbol.category.lower() == "futures":
        current_index_price = get_futures_index_price(symbol_manager_contract, symbol)
        slippage = slippage_pct / Decimal("100")
        if trade_volume_18 >= 0:
            price_limit = current_index_price * (Decimal("1") + slippage)
        else:
            price_limit = current_index_price * (Decimal("1") - slippage)
        if price_limit <= 0:
            raise RuntimeError(f"Computed non-positive price limit: {price_limit}")
        print(
            "Auto price limit:",
            f"index={format_decimal(current_index_price)}",
            f"slippage_pct={format_decimal(slippage_pct)}",
            f"limit={format_decimal(price_limit)}",
        )
        return price_limit

    if symbol.category.lower() != "option":
        raise RuntimeError("Automatic price-limit discovery currently supports futures and options only")

    if symbol.alpha is None or symbol.strike_price is None:
        raise RuntimeError(f"Option symbol metadata is incomplete for {symbol.symbol}")

    query_price_symbol = get_option_query_price_symbol(symbol)
    query_volatility_symbol = f"VOL-{query_price_symbol}"
    oracle_rows = fetch_oracles(graph_url, [query_price_symbol, query_volatility_symbol])
    symbol_state = fetch_symbol_state(graph_url, pool.symbol_manager, symbol.symbol_id) or {}

    if query_price_symbol not in oracle_rows:
        raise RuntimeError(f"Oracle price {query_price_symbol} was not found for {symbol.symbol}")
    if query_volatility_symbol not in oracle_rows:
        raise RuntimeError(f"Oracle volatility {query_volatility_symbol} was not found for {symbol.symbol}")

    current_index_price_float = float(to_decimal(oracle_rows[query_price_symbol]["value"]))
    volatility_float = float(to_decimal(oracle_rows[query_volatility_symbol]["value"]))
    strike_price_float = float(symbol.strike_price)
    theoretical_price, _intrinsic_value, delta, _gamma, time_value, u = calculate_everlasting_option(
        current_index_price_float,
        strike_price_float,
        volatility_float,
        symbol.is_call,
    )
    net_volume_float = float(decimal_or_zero(symbol_state.get("netVolume")))
    trade_volume_float = float(from_18(trade_volume_18))
    k = calculate_option_k(
        current_index_price_float,
        theoretical_price,
        float(symbol.alpha),
        delta,
        float(pool.total_liquidity),
        float(pool.lps_pnl),
    )
    mark_price = calculate_mark_price(theoretical_price, k, net_volume_float)
    price_limit_float = calculate_price_limit(
        theoretical_price,
        k,
        trade_volume_float,
        net_volume_float,
        float(slippage_pct / Decimal("100")),
        mark_price,
        current_index_price_float,
        strike=strike_price_float,
        time_value_delta_u=(time_value, delta, u),
        volatility=volatility_float,
    )
    price_limit = to_decimal(str(price_limit_float))
    if price_limit <= 0:
        raise RuntimeError(f"Computed non-positive price limit: {price_limit}")
    print(
        "Auto price limit:",
        f"symbol={symbol.symbol}",
        f"category={symbol.category}",
        f"index={format_decimal(to_decimal(str(current_index_price_float)))}",
        f"mark={format_decimal(to_decimal(str(mark_price)))}",
        f"net_volume={format_decimal(to_decimal(str(net_volume_float)))}",
        f"slippage_pct={format_decimal(slippage_pct)}",
        f"limit={format_decimal(price_limit)}",
    )
    return price_limit


def validate_trade_volume(symbol: SymbolMetadata, trade_volume_18: int) -> None:
    min_trade_volume_18 = to_18(symbol.min_trade_volume)
    if abs(trade_volume_18) < min_trade_volume_18:
        raise RuntimeError(
            f"trade_volume is below the minimum: {format_decimal(symbol.min_trade_volume)}"
        )
    if abs(trade_volume_18) % min_trade_volume_18 != 0:
        raise RuntimeError(
            f"trade_volume must be an integer multiple of {format_decimal(symbol.min_trade_volume)}"
        )


def load_session_key_if_present(
    explicit_private_key: str,
    session_key_path: Path,
) -> SessionKey | None:
    if explicit_private_key:
        wallet = Account.from_key(explicit_private_key)
        return SessionKey(address=wallet.address, private_key=explicit_private_key, source="env/cli")

    if not session_key_path.exists():
        return None

    payload = json.loads(session_key_path.read_text())
    private_key = payload["privateKey"]
    wallet = Account.from_key(private_key)
    return SessionKey(address=wallet.address, private_key=private_key, source=str(session_key_path))


def load_or_create_session_key(
    explicit_private_key: str,
    session_key_path: Path,
) -> SessionKey:
    existing = load_session_key_if_present(explicit_private_key, session_key_path)
    if existing:
        return existing

    wallet = Account.create()
    session_key_path.write_text(
        json.dumps(
            {
                "address": wallet.address,
                "privateKey": wallet.key.hex(),
                "createdAt": int(time.time()),
            },
            indent=2,
        )
        + "\n"
    )
    return SessionKey(address=wallet.address, private_key=wallet.key.hex(), source=str(session_key_path))


def pack_two_uint128(high: int, low: int) -> bytes:
    if high < 0 or low < 0:
        raise RuntimeError("Packed gas values must be non-negative")
    if high >= 1 << 128 or low >= 1 << 128:
        raise RuntimeError("Packed gas values exceed uint128")
    return ((high << 128) | low).to_bytes(32, "big")


def build_paymaster_and_data(
    paymaster: str,
    verification_gas_limit: int,
    post_op_gas_limit: int,
    paymaster_data: str = "0x",
) -> bytes:
    if not paymaster or paymaster in {"0x", ZERO_ADDRESS}:
        return b""
    return (
        bytes(HexBytes(paymaster))
        + verification_gas_limit.to_bytes(16, "big")
        + post_op_gas_limit.to_bytes(16, "big")
        + bytes(HexBytes(paymaster_data))
    )


def build_init_code(factory: str | None, factory_data: str | None) -> bytes:
    if not factory or not factory_data:
        return b""
    return bytes(HexBytes(factory)) + bytes(HexBytes(factory_data))


def derive_smart_account_address(factory_contract, owner: str, salt: int, web3: Web3) -> str:
    return to_checksum(web3, factory_contract.functions.getAddress(to_checksum(web3, owner), salt).call())


def get_smart_account_status(dchain_web3: Web3, address: str) -> SmartAccountStatus:
    deployed = bool(dchain_web3.eth.get_code(to_checksum(dchain_web3, address)))
    if not deployed:
        return SmartAccountStatus(address=to_checksum(dchain_web3, address), deployed=False, session_key=None, session_key_valid=False)

    smart_account_contract = get_contract(dchain_web3, address, "EvmAccount.json")
    session_key = smart_account_contract.functions.sessionKey().call()
    session_key_valid = smart_account_contract.functions.isSessionKeyValid().call()
    if session_key == ZERO_ADDRESS:
        session_key = None

    return SmartAccountStatus(
        address=to_checksum(dchain_web3, address),
        deployed=True,
        session_key=to_checksum(dchain_web3, session_key) if session_key else None,
        session_key_valid=bool(session_key_valid),
    )


def wait_for_smart_account_status(
    dchain_web3: Web3,
    address: str,
    expected_session_key: str,
    timeout: int,
    poll_interval: float,
) -> SmartAccountStatus:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_smart_account_status(dchain_web3, address)
        if (
            status.deployed
            and status.session_key
            and status.session_key.lower() == expected_session_key.lower()
            and status.session_key_valid
        ):
            return status
        time.sleep(poll_interval)
    raise TimeoutError("Timed out waiting for the smart account session key to become active")


def build_factory_data(factory_contract, owner: str, salt: int) -> str:
    return encode_contract_call(
        factory_contract,
        "createAccount",
        [Web3.to_checksum_address(owner), salt],
    )


def build_user_operation(
    sender: str,
    nonce: int,
    call_data: str,
    config: UserOperationConfig,
    factory: str | None = None,
    factory_data: str | None = None,
) -> dict[str, Any]:
    user_op = {
        "sender": sender,
        "nonce": nonce,
        "callData": call_data,
        "signature": "0x",
        "callGasLimit": config.call_gas_limit,
        "verificationGasLimit": config.verification_gas_limit,
        "preVerificationGas": config.pre_verification_gas,
        "maxFeePerGas": config.max_fee_per_gas,
        "maxPriorityFeePerGas": config.max_priority_fee_per_gas,
        "paymaster": config.paymaster,
        "paymasterVerificationGasLimit": config.paymaster_verification_gas_limit,
        "paymasterPostOpGasLimit": config.paymaster_post_op_gas_limit,
        "paymasterData": "0x",
    }
    if factory and factory_data:
        user_op["factory"] = factory
        user_op["factoryData"] = factory_data
    return user_op


def user_operation_for_entry_point(user_op: dict[str, Any]) -> dict[str, Any]:
    return {
        "sender": user_op["sender"],
        "nonce": int(user_op["nonce"]),
        "initCode": build_init_code(user_op.get("factory"), user_op.get("factoryData")),
        "callData": bytes(HexBytes(user_op["callData"])),
        "accountGasLimits": pack_two_uint128(
            int(user_op["verificationGasLimit"]),
            int(user_op["callGasLimit"]),
        ),
        "preVerificationGas": int(user_op["preVerificationGas"]),
        "gasFees": pack_two_uint128(
            int(user_op["maxPriorityFeePerGas"]),
            int(user_op["maxFeePerGas"]),
        ),
        "paymasterAndData": build_paymaster_and_data(
            user_op["paymaster"],
            int(user_op["paymasterVerificationGasLimit"]),
            int(user_op["paymasterPostOpGasLimit"]),
            user_op.get("paymasterData", "0x"),
        ),
        "signature": bytes(HexBytes(user_op["signature"])),
    }


def sign_hash(private_key: str, digest: bytes | str) -> str:
    digest_bytes = HexBytes(digest)
    signer = getattr(Account, "_sign_hash", None)
    if signer is not None:
        signed = signer(digest_bytes, private_key=private_key)
        signature = getattr(signed, "signature", None)
        if signature is not None:
            return Web3.to_hex(signature)

    signing_key = keys.PrivateKey(bytes(HexBytes(private_key)))
    signature = signing_key.sign_msg_hash(bytes(digest_bytes))
    return Web3.to_hex(
        signature.r.to_bytes(32, "big")
        + signature.s.to_bytes(32, "big")
        + bytes([signature.v + 27])
    )


def sign_user_operation(user_op: dict[str, Any], signer_private_key: str, entry_point_contract) -> tuple[dict[str, Any], str]:
    entry_point_user_op = user_operation_for_entry_point(user_op)
    user_op_hash = entry_point_contract.functions.getUserOpHash(entry_point_user_op).call()
    user_op["signature"] = sign_hash(signer_private_key, user_op_hash)
    return user_op, Web3.to_hex(user_op_hash)


def user_operation_for_bundler(user_op: dict[str, Any]) -> dict[str, Any]:
    rpc_user_op = {
        "sender": user_op["sender"],
        "nonce": hex(int(user_op["nonce"])),
        "callData": user_op["callData"],
        "signature": user_op["signature"],
        "callGasLimit": hex(int(user_op["callGasLimit"])),
        "verificationGasLimit": hex(int(user_op["verificationGasLimit"])),
        "preVerificationGas": hex(int(user_op["preVerificationGas"])),
        "maxFeePerGas": hex(int(user_op["maxFeePerGas"])),
        "maxPriorityFeePerGas": hex(int(user_op["maxPriorityFeePerGas"])),
        "paymaster": user_op["paymaster"],
        "paymasterVerificationGasLimit": hex(int(user_op["paymasterVerificationGasLimit"])),
        "paymasterPostOpGasLimit": hex(int(user_op["paymasterPostOpGasLimit"])),
        "paymasterData": user_op["paymasterData"],
    }
    if user_op.get("factory") and user_op.get("factoryData"):
        rpc_user_op["factory"] = user_op["factory"]
        rpc_user_op["factoryData"] = user_op["factoryData"]
    return rpc_user_op


def wait_for_user_operation_receipt(
    bundler_rpc: str,
    user_op_hash: str,
    timeout: int,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        receipt = json_rpc_request(bundler_rpc, "eth_getUserOperationReceipt", [user_op_hash])
        if receipt is not None:
            return receipt
        time.sleep(poll_interval)
    raise TimeoutError(f"Timed out waiting for user operation receipt {user_op_hash}")


def submit_user_operation(
    user_op: dict[str, Any],
    config: UserOperationConfig,
    timeout: int,
    poll_interval: float,
) -> tuple[str, dict[str, Any]]:
    bundler_user_op = user_operation_for_bundler(user_op)
    user_op_hash = json_rpc_request(
        config.bundler_rpc,
        "eth_sendUserOperation",
        [bundler_user_op, config.entry_point],
    )
    receipt = wait_for_user_operation_receipt(
        config.bundler_rpc,
        user_op_hash,
        timeout,
        poll_interval,
    )
    success = receipt.get("success")
    if success is False:
        raise RuntimeError(f"User operation failed: {json.dumps(receipt, sort_keys=True)}")
    return user_op_hash, receipt


def ensure_trading_enabled(
    dchain_web3: Web3,
    factory_contract,
    entry_point_contract,
    owner: str,
    owner_private_key: str,
    salt: int,
    session_key: SessionKey,
    config: UserOperationConfig,
    timeout: int,
    poll_interval: float,
) -> SmartAccountStatus:
    smart_account_address = derive_smart_account_address(factory_contract, owner, salt, dchain_web3)
    status = get_smart_account_status(dchain_web3, smart_account_address)
    if (
        status.deployed
        and status.session_key
        and status.session_key.lower() == session_key.address.lower()
        and status.session_key_valid
    ):
        print(f"Smart account ready: {status.address}")
        print(f"Session key already active: {status.session_key}")
        return status

    smart_account_contract = get_contract(dchain_web3, smart_account_address, "EvmAccount.json")
    valid_until = int(time.time()) + config.session_key_valid_seconds
    inner_call = encode_contract_call(
        smart_account_contract,
        "setSessionKey",
        [to_checksum(dchain_web3, session_key.address), valid_until],
    )
    execute_call = encode_contract_call(
        smart_account_contract,
        "execute",
        [to_checksum(dchain_web3, smart_account_address), 0, inner_call],
    )
    nonce = entry_point_contract.functions.getNonce(to_checksum(dchain_web3, smart_account_address), 0).call()
    factory_data = None if status.deployed else build_factory_data(factory_contract, owner, salt)
    user_op = build_user_operation(
        sender=to_checksum(dchain_web3, smart_account_address),
        nonce=nonce,
        call_data=execute_call,
        config=config,
        factory=None if status.deployed else to_checksum(dchain_web3, factory_contract.address),
        factory_data=factory_data,
    )
    user_op, op_hash_for_signing = sign_user_operation(user_op, owner_private_key, entry_point_contract)
    print("Submitting Enable Trading user operation")
    print(f"  smartAccount={smart_account_address}")
    print(f"  sessionKey={session_key.address}")
    print(f"  userOpHashForSigning={op_hash_for_signing}")
    submitted_user_op_hash, receipt = submit_user_operation(user_op, config, timeout, poll_interval)
    transaction_hash = receipt.get("transactionHash") or receipt.get("receipt", {}).get("transactionHash")
    print(f"  bundlerUserOpHash={submitted_user_op_hash}")
    if transaction_hash:
        print(f"  dChainTx={transaction_hash}")
    return wait_for_smart_account_status(
        dchain_web3,
        smart_account_address,
        session_key.address,
        timeout,
        poll_interval,
    )


def execute_engine_trade_via_user_operation(
    dchain_web3: Web3,
    smart_account_address: str,
    engine_contract,
    entry_point_contract,
    session_key_private_key: str,
    p_token_id: int,
    symbol: SymbolMetadata,
    trade_volume_18: int,
    price_limit_18: int,
    config: UserOperationConfig,
    timeout: int,
    poll_interval: float,
) -> tuple[str, dict[str, Any]]:
    smart_account_contract = get_contract(dchain_web3, smart_account_address, "EvmAccount.json")
    trade_call = encode_contract_call(
        engine_contract,
        "trade",
        [p_token_id, symbol.symbol_id, [trade_volume_18, price_limit_18]],
    )
    execute_call = encode_contract_call(
        smart_account_contract,
        "execute",
        [to_checksum(dchain_web3, engine_contract.address), 0, trade_call],
    )
    nonce = entry_point_contract.functions.getNonce(to_checksum(dchain_web3, smart_account_address), 0).call()
    user_op = build_user_operation(
        sender=to_checksum(dchain_web3, smart_account_address),
        nonce=nonce,
        call_data=execute_call,
        config=config,
    )
    user_op, op_hash_for_signing = sign_user_operation(user_op, session_key_private_key, entry_point_contract)
    print("Submitting engine.trade through the dChain smart account")
    print(f"  smartAccount={smart_account_address}")
    print(f"  userOpHashForSigning={op_hash_for_signing}")
    return submit_user_operation(user_op, config, timeout, poll_interval)


def execute_engine_remove_margin_via_user_operation(
    dchain_web3: Web3,
    smart_account_address: str,
    smart_account_deployed: bool,
    engine_contract,
    entry_point_contract,
    owner_private_key: str,
    p_token_id: int,
    b_token_id: Any,
    remove_b_amount_18: int,
    config: UserOperationConfig,
    timeout: int,
    poll_interval: float,
    factory_contract=None,
    owner: str | None = None,
    salt: int | None = None,
) -> tuple[str, dict[str, Any]]:
    if not smart_account_deployed and (factory_contract is None or owner is None or salt is None):
        raise RuntimeError("factory_contract, owner, and salt are required when the smart account is not deployed")

    smart_account_contract = get_contract(dchain_web3, smart_account_address, "EvmAccount.json")
    remove_call = encode_contract_call(
        engine_contract,
        "executeRemoveMargin",
        [p_token_id, Web3.to_hex(normalize_bytes32(b_token_id)), remove_b_amount_18],
    )
    execute_call = encode_contract_call(
        smart_account_contract,
        "execute",
        [to_checksum(dchain_web3, engine_contract.address), 0, remove_call],
    )
    nonce = entry_point_contract.functions.getNonce(to_checksum(dchain_web3, smart_account_address), 0).call()
    factory_data = None if smart_account_deployed else build_factory_data(factory_contract, owner, salt)
    user_op = build_user_operation(
        sender=to_checksum(dchain_web3, smart_account_address),
        nonce=nonce,
        call_data=execute_call,
        config=config,
        factory=None if smart_account_deployed else to_checksum(dchain_web3, factory_contract.address),
        factory_data=factory_data,
    )
    user_op, op_hash_for_signing = sign_user_operation(user_op, owner_private_key, entry_point_contract)
    print("Submitting engine.executeRemoveMargin through the dChain smart account")
    print(f"  smartAccount={smart_account_address}")
    print(f"  userOpHashForSigning={op_hash_for_signing}")
    return submit_user_operation(user_op, config, timeout, poll_interval)


def resolve_account(args: argparse.Namespace, require_private_key: bool = False) -> tuple[str, str]:
    private_key = getattr(args, "private_key", "") or ""
    account = getattr(args, "account", "") or ""

    if private_key:
        owner_wallet = Account.from_key(private_key)
        if account and owner_wallet.address.lower() != account.lower():
            raise RuntimeError("--account does not match --private-key")
        account = owner_wallet.address

    if not account:
        raise RuntimeError("--account or --private-key is required")
    if require_private_key and not private_key:
        raise RuntimeError("--private-key is required")

    return account, private_key


def connect_web3_clients(args: argparse.Namespace) -> tuple[Web3, Web3, int, int]:
    ichain_web3 = Web3(Web3.HTTPProvider(args.ichain_rpc, request_kwargs={"timeout": 30}))
    dchain_web3 = Web3(Web3.HTTPProvider(args.dchain_rpc, request_kwargs={"timeout": 30}))
    require_connected(ichain_web3, f"iChain RPC {args.ichain_rpc}")
    require_connected(dchain_web3, f"dChain RPC {args.dchain_rpc}")
    return ichain_web3, dchain_web3, ichain_web3.eth.chain_id, dchain_web3.eth.chain_id


def build_user_operation_config(args: argparse.Namespace, dchain_chain_id: int, dchain_web3: Web3) -> UserOperationConfig:
    return UserOperationConfig(
        bundler_rpc=args.bundler_rpc,
        entry_point=to_checksum(dchain_web3, args.entry_point),
        paymaster=to_checksum(dchain_web3, args.paymaster),
        dchain_chain_id=dchain_chain_id,
        call_gas_limit=args.call_gas_limit,
        verification_gas_limit=args.verification_gas_limit,
        pre_verification_gas=args.pre_verification_gas,
        max_fee_per_gas=args.max_fee_per_gas,
        max_priority_fee_per_gas=args.max_priority_fee_per_gas,
        paymaster_verification_gas_limit=args.paymaster_verification_gas_limit,
        paymaster_post_op_gas_limit=args.paymaster_post_op_gas_limit,
        session_key_valid_seconds=args.session_key_valid_seconds,
    )


def print_pool_selection(pool: PoolMetadata, zone: ZoneConfig | None, selection_source: str) -> None:
    print("Using pool:")
    print(f"  selection={selection_source}")
    if zone:
        print(f"  zone={zone.label} ({zone.key})")
    print(f"  gateway={pool.gateway_address}")
    print(f"  engine={pool.engine_address}")
    print(f"  symbolManager={pool.symbol_manager}")
    print(f"  smartAccountFactory={pool.smart_account_factory}")


def print_active_ptoken_state(active_state: ActivePTokenState) -> None:
    print("Active pToken:")
    print(f"  pTokenId={active_state.p_token_id}")
    print(f"  gateway={active_state.gateway_address}")
    if active_state.zone_key:
        print(f"  zone={active_state.zone_key}")
    print(
        f"  margin_token={active_state.margin_token_symbol} ({active_state.margin_token_address})"
    )


def build_active_ptoken_state(
    account: str,
    ichain_chain_id: int,
    dchain_chain_id: int,
    p_token_id: int,
    pool: PoolMetadata,
    zone: ZoneConfig | None,
    market: MarketMetadata,
    previous_created_at: int | None = None,
) -> ActivePTokenState:
    now = int(time.time())
    return ActivePTokenState(
        account=account,
        ichain_chain_id=ichain_chain_id,
        dchain_chain_id=dchain_chain_id,
        p_token_id=p_token_id,
        gateway_address=pool.gateway_address,
        zone_key=zone.key if zone else None,
        margin_token_address=market.asset_address,
        margin_token_symbol=market.asset_symbol,
        margin_token_decimals=market.asset_decimals,
        created_at=previous_created_at or now,
        updated_at=now,
    )


def print_td_account_hint(td_account: str | None, owner_account: str, smart_account_address: str | None = None) -> None:
    if not td_account:
        return
    print(f"dChain tdState.account={td_account}")
    if td_account.lower() == owner_account.lower():
        print("  tdState.account tracks the owner EOA; smart-account execution remains session-key based")
    elif smart_account_address and td_account.lower() == smart_account_address.lower():
        print("  tdState.account matches the derived smart-account address")
    elif smart_account_address:
        print("  Note: tdState.account does not match either the owner EOA or the derived smart-account address")


def get_unique_markets(pools: list[PoolMetadata]) -> list[MarketMetadata]:
    by_address: dict[str, MarketMetadata] = {}
    for pool in pools:
        for market in pool.markets:
            by_address.setdefault(market.asset_address.lower(), market)
    return sorted(by_address.values(), key=lambda market: (market.asset_symbol.upper(), market.asset_address.lower()))


def get_wallet_token_balance(ichain_web3: Web3, market: MarketMetadata, account: str) -> Decimal:
    if market.asset_address.lower() == ETH_ADDRESS.lower():
        return from_18(ichain_web3.eth.get_balance(to_checksum(ichain_web3, account)))
    erc20 = get_contract(ichain_web3, market.asset_address, "Erc20.json")
    balance = erc20.functions.balanceOf(to_checksum(ichain_web3, account)).call()
    return from_token_units(balance, market.asset_decimals)


def wait_for_wallet_balance_increase(
    ichain_web3: Web3,
    market: MarketMetadata,
    account: str,
    baseline_balance: Decimal,
    timeout: int,
    poll_interval: float,
) -> Decimal | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        current_balance = get_wallet_token_balance(ichain_web3, market, account)
        if current_balance > baseline_balance:
            return current_balance
        time.sleep(poll_interval)
    return None


def command_init_p_token(args: argparse.Namespace) -> None:
    account, private_key = resolve_account(args, require_private_key=True)
    ichain_web3, dchain_web3, ichain_chain_id, dchain_chain_id = connect_web3_clients(args)
    pools = fetch_pool_metadatas(args.graph_url, ichain_chain_id)

    current_active = load_active_ptoken_state(LOCAL_ACTIVE_PTOKEN_PATH)
    if current_active is not None and not args.replace_active:
        raise RuntimeError(
            "An active pToken is already configured. "
            f"active={current_active.p_token_id}. "
            "Use --replace-active if you want to replace it."
        )

    print(f"Resolved iChain chainId={ichain_chain_id}")
    print(f"Resolved dChain chainId={dchain_chain_id}")

    if args.existing_p_token_id is not None:
        td_states = fetch_td_states(args.graph_url, ichain_chain_id, account)
        td_state_row = find_td_state_row(td_states, args.existing_p_token_id)
        if td_state_row is None:
            raise RuntimeError(f"Could not find existing pTokenId={args.existing_p_token_id} for account {account}")
        pool, _td_state, zone, selection_source = resolve_pool_by_p_token_id(
            pools,
            dchain_web3,
            args.existing_p_token_id,
            expected_account=account,
        )
        b_token = td_state_row.get("bToken")
        if not b_token or not Web3.is_address(b_token):
            raise RuntimeError(f"Could not determine the margin token for pTokenId={args.existing_p_token_id}")
        market = find_market_by_address(pool, b_token)
        active_state = build_active_ptoken_state(
            account=account,
            ichain_chain_id=ichain_chain_id,
            dchain_chain_id=dchain_chain_id,
            p_token_id=args.existing_p_token_id,
            pool=pool,
            zone=zone,
            market=market,
        )
        save_active_ptoken_state(LOCAL_ACTIVE_PTOKEN_PATH, active_state)
        print_pool_selection(pool, zone, selection_source)
        print("Adopted existing pToken as the active demo state")
        print_active_ptoken_state(active_state)
        print(f"  state_file={LOCAL_ACTIVE_PTOKEN_PATH}")
        return

    if not args.margin_token:
        raise RuntimeError("--margin-token is required when creating a new pToken")
    if args.margin_amount is None:
        raise RuntimeError("--margin-amount is required when creating a new pToken")

    if getattr(args, "symbol", None):
        pool, _symbol, zone, selection_source = select_pool_and_symbol(
            pools,
            ichain_chain_id,
            args.symbol,
            args.category,
            args.gateway_address,
            args.gateway_index,
            args.zone,
        )
    else:
        pool, zone, selection_source = select_pool_without_symbol(
            pools,
            ichain_chain_id,
            args.gateway_address,
            args.gateway_index,
            args.zone,
        )
    market = find_market(pool, args.margin_token)

    print_pool_selection(pool, zone, selection_source)
    print("Init-pToken configuration:")
    print(f"  margin_token={market.asset_symbol} ({market.asset_address})")
    print(f"  margin_amount={args.margin_amount}")

    gateway = get_contract(ichain_web3, pool.gateway_address, "GatewayImplementation.json")
    engine = get_contract(dchain_web3, pool.engine_address, "EngineImplementation.json")

    if market.asset_address.lower() != ETH_ADDRESS.lower():
        erc20 = get_contract(ichain_web3, market.asset_address, "Erc20.json")
        approve_if_needed(
            erc20,
            account,
            pool.gateway_address,
            to_token_units(args.margin_amount, market.asset_decimals),
            ichain_web3,
            private_key,
        )

    print("Submitting requestAddMargin on the iChain gateway")
    receipt, p_token_id, signature = request_add_margin(
        gateway,
        market,
        to_decimal(args.margin_amount),
        ichain_web3,
        account,
        private_key,
        p_token_id=0,
    )
    print(f"requestAddMargin tx: {receipt.transactionHash.hex()}")
    print(f"requestAddMargin signature: {signature}")
    print(f"pTokenId={p_token_id}")

    td_state = wait_for_td_state(engine, p_token_id, args.timeout, args.poll_interval)
    print_td_account_hint(bytes32_to_address(td_state[1]), account)

    active_state = build_active_ptoken_state(
        account=account,
        ichain_chain_id=ichain_chain_id,
        dchain_chain_id=dchain_chain_id,
        p_token_id=p_token_id,
        pool=pool,
        zone=zone,
        market=market,
    )
    save_active_ptoken_state(LOCAL_ACTIVE_PTOKEN_PATH, active_state)
    print("Saved the active demo pToken state")
    print_active_ptoken_state(active_state)
    print(f"  state_file={LOCAL_ACTIVE_PTOKEN_PATH}")


def command_status(args: argparse.Namespace) -> None:
    account, _private_key = resolve_account(args, require_private_key=False)
    ichain_web3, dchain_web3, ichain_chain_id, dchain_chain_id = connect_web3_clients(args)
    pools = fetch_pool_metadatas(args.graph_url, ichain_chain_id)
    td_states = fetch_td_states(args.graph_url, ichain_chain_id, account)

    print(f"Resolved iChain chainId={ichain_chain_id}")
    print(f"Resolved dChain chainId={dchain_chain_id}")
    print("Account status:")
    print(f"  owner={account}")

    factory_address = pools[0].smart_account_factory
    if len({pool.smart_account_factory.lower() for pool in pools}) > 1:
        print("  Warning: pools expose different smart-account factories; using the first pool's factory for status")
    factory_contract = get_contract(dchain_web3, factory_address, "EvmAccountFactory.json")
    smart_account_address = derive_smart_account_address(factory_contract, account, ichain_chain_id, dchain_web3)
    smart_account_status = get_smart_account_status(dchain_web3, smart_account_address)
    print(f"  smart_account={smart_account_status.address}")
    print(f"  smart_account_deployed={smart_account_status.deployed}")
    print(f"  active_session_key={smart_account_status.session_key or 'none'}")
    print(f"  active_session_key_valid={smart_account_status.session_key_valid}")

    local_session_key = load_session_key_if_present(args.session_key_private, LOCAL_SESSION_KEY_PATH)
    if local_session_key:
        print(f"  local_session_key={local_session_key.address}")
        print(f"  local_session_key_source={local_session_key.source}")
    else:
        print("  local_session_key=none")

    active_state = load_active_ptoken_state(LOCAL_ACTIVE_PTOKEN_PATH)
    if active_state is None:
        print("Active pToken:")
        print("  none")
    else:
        print_active_ptoken_state(active_state)
        print(f"  state_file={LOCAL_ACTIVE_PTOKEN_PATH}")
        if (
            active_state.account.lower() == account.lower()
            and active_state.ichain_chain_id == ichain_chain_id
            and active_state.dchain_chain_id == dchain_chain_id
        ):
            td_state_row = find_td_state_row(td_states, active_state.p_token_id)
            if td_state_row is None:
                print("  warning=active pToken was not found in the live tdState query")
            else:
                positions = td_state_row.get("positions", [])
                open_positions = [position for position in positions if decimal_or_zero(position.get("volume")) != 0]
                print(f"  bAmount={format_decimal(decimal_or_zero(td_state_row.get('bAmount')))}")
                print(f"  b0Amount={format_decimal(decimal_or_zero(td_state_row.get('b0Amount')))}")
                print(f"  cumulativePnl={format_decimal(decimal_or_zero(td_state_row.get('cumulativePnl')))}")
                print(f"  open_positions={len(open_positions)}")
        else:
            print("  warning=active pToken does not match the current account or network")

    print("Pools:")
    for pool in pools:
        zone = infer_known_zone(ichain_chain_id, pool.gateway_address)
        zone_text = f"{zone.label} ({zone.key})" if zone else "unlabeled"
        market_symbols = ", ".join(sorted(market.asset_symbol for market in pool.markets))
        print(f"  {zone_text}: gateway={pool.gateway_address} markets=[{market_symbols}] symbols={len(pool.symbols)}")

    print("iChain balances:")
    for market in get_unique_markets(pools):
        balance = get_wallet_token_balance(ichain_web3, market, account)
        print(f"  {market.asset_symbol}={format_decimal(balance)}")

    open_positions = sum(
        1
        for td_state in td_states
        for position in td_state.get("positions", [])
        if decimal_or_zero(position.get("volume")) != 0
    )
    print("Portfolio:")
    print(f"  td_states={len(td_states)}")
    print(f"  open_positions={open_positions}")
    if active_state is None and len(td_states) == 1:
        print("  discovered_existing_pTokenId=" + str(td_states[0]["pTokenId"]))
        print("  note=Run `python demo.py init-p-token --existing-p-token-id ...` to adopt it as the active demo pToken.")


def command_positions(args: argparse.Namespace) -> None:
    account, _private_key = resolve_account(args, require_private_key=False)
    _ichain_web3, _dchain_web3, ichain_chain_id, dchain_chain_id = connect_web3_clients(args)
    pools = fetch_pool_metadatas(args.graph_url, ichain_chain_id)
    active_state = require_active_ptoken_state(account, ichain_chain_id, dchain_chain_id)
    pool, zone, selection_source = resolve_pool_from_active_state(pools, active_state)
    td_states = fetch_td_states(args.graph_url, ichain_chain_id, account)
    td_state = find_td_state_row(td_states, active_state.p_token_id)

    print(f"Resolved iChain chainId={ichain_chain_id}")
    print(f"Resolved dChain chainId={dchain_chain_id}")
    print_pool_selection(pool, zone, selection_source)
    print_active_ptoken_state(active_state)
    if td_state is None:
        print("Active pToken was not found in the live tdState query.")
        return

    print(f"  bAmount={format_decimal(decimal_or_zero(td_state.get('bAmount')))}")
    print(f"  b0Amount={format_decimal(decimal_or_zero(td_state.get('b0Amount')))}")
    print(f"  cumulativePnl={format_decimal(decimal_or_zero(td_state.get('cumulativePnl')))}")
    print(f"  liquidated={bool(td_state.get('liquidated'))}")

    positions = td_state.get("positions", [])
    if args.symbol:
        positions = [position for position in positions if position.get("symbol", "").upper() == args.symbol.upper()]

    if not positions:
        print("  positions=none")
        return

    for position in positions:
        volume = decimal_or_zero(position.get("volume"))
        direction = "flat"
        if volume > 0:
            direction = "long"
        elif volume < 0:
            direction = "short"
        print(
            f"  {position['symbol']}:",
            f"direction={direction}",
            f"volume={format_decimal(volume)}",
            f"cost={format_decimal(decimal_or_zero(position.get('cost')))}",
            f"cumulativeFundingPerVolume={format_decimal(decimal_or_zero(position.get('cumulativeFundingPerVolume')))}",
        )


def command_add_margin(args: argparse.Namespace) -> None:
    account, private_key = resolve_account(args, require_private_key=True)
    ichain_web3, dchain_web3, ichain_chain_id, dchain_chain_id = connect_web3_clients(args)
    pools = fetch_pool_metadatas(args.graph_url, ichain_chain_id)
    active_state = require_active_ptoken_state(account, ichain_chain_id, dchain_chain_id)
    pool, zone, selection_source = resolve_pool_from_active_state(pools, active_state)
    market = find_market_by_address(pool, active_state.margin_token_address)

    print(f"Resolved iChain chainId={ichain_chain_id}")
    print(f"Resolved dChain chainId={dchain_chain_id}")
    print_pool_selection(pool, zone, selection_source)
    print_active_ptoken_state(active_state)
    print("Add-margin configuration:")
    print(f"  margin_token={market.asset_symbol} ({market.asset_address})")
    print(f"  margin_amount={args.margin_amount}")

    gateway = get_contract(ichain_web3, pool.gateway_address, "GatewayImplementation.json")
    engine = get_contract(dchain_web3, pool.engine_address, "EngineImplementation.json")

    if market.asset_address.lower() != ETH_ADDRESS.lower():
        erc20 = get_contract(ichain_web3, market.asset_address, "Erc20.json")
        approve_if_needed(
            erc20,
            account,
            pool.gateway_address,
            to_token_units(args.margin_amount, market.asset_decimals),
            ichain_web3,
            private_key,
        )

    print("Submitting requestAddMargin on the iChain gateway")
    receipt, p_token_id, signature = request_add_margin(
        gateway,
        market,
        to_decimal(args.margin_amount),
        ichain_web3,
        account,
        private_key,
        p_token_id=active_state.p_token_id,
    )
    print(f"requestAddMargin tx: {receipt.transactionHash.hex()}")
    print(f"requestAddMargin signature: {signature}")
    print(f"pTokenId={p_token_id}")

    if p_token_id != active_state.p_token_id:
        raise RuntimeError(
            f"requestAddMargin returned a different pTokenId ({p_token_id}) than the active one ({active_state.p_token_id})"
        )

    td_state = wait_for_td_state(
        engine,
        p_token_id,
        args.timeout,
        args.poll_interval,
    )
    print_td_account_hint(bytes32_to_address(td_state[1]), account)
    save_active_ptoken_state(
        LOCAL_ACTIVE_PTOKEN_PATH,
        build_active_ptoken_state(
            account=account,
            ichain_chain_id=ichain_chain_id,
            dchain_chain_id=dchain_chain_id,
            p_token_id=active_state.p_token_id,
            pool=pool,
            zone=zone,
            market=market,
            previous_created_at=active_state.created_at,
        ),
    )


def run_trade_command(args: argparse.Namespace, close_position: bool) -> None:
    account, private_key = resolve_account(args, require_private_key=True)
    _ichain_web3, dchain_web3, ichain_chain_id, dchain_chain_id = connect_web3_clients(args)
    pools = fetch_pool_metadatas(args.graph_url, ichain_chain_id)
    active_state = require_active_ptoken_state(account, ichain_chain_id, dchain_chain_id)
    pool, zone, selection_source = resolve_pool_from_active_state(pools, active_state)
    symbol = find_symbol(pool, args.symbol, args.category)
    if symbol.category.lower() == "gamma":
        raise RuntimeError("This demo only supports 2-parameter trades. Gamma symbols need 4 trade params.")
    engine = get_contract(dchain_web3, pool.engine_address, "EngineImplementation.json")
    td_state = get_td_state(engine, active_state.p_token_id)
    td_account = bytes32_to_address(td_state[1])
    if not td_account:
        raise RuntimeError(f"Active pTokenId={active_state.p_token_id} was not found on dChain")

    print(f"Resolved iChain chainId={ichain_chain_id}")
    print(f"Resolved dChain chainId={dchain_chain_id}")
    print_pool_selection(pool, zone, selection_source)
    print_active_ptoken_state(active_state)
    print("Trade configuration:")
    print(f"  symbol={symbol.symbol} ({symbol.category})")
    print(f"  pTokenId={active_state.p_token_id}")

    symbol_manager = get_contract(dchain_web3, pool.symbol_manager, "SymbolManager.json")
    smart_account_factory = get_contract(dchain_web3, pool.smart_account_factory, "EvmAccountFactory.json")
    entry_point = get_contract(dchain_web3, args.entry_point, "EntryPoint.json")

    session_key = load_or_create_session_key(args.session_key_private, LOCAL_SESSION_KEY_PATH)
    print("Smart-account bootstrap:")
    print(f"  owner={account}")
    print(f"  salt={ichain_chain_id}")
    print(f"  session_key={session_key.address}")
    print(f"  session_key_source={session_key.source}")

    user_op_config = build_user_operation_config(args, dchain_chain_id, dchain_web3)
    smart_account_status = ensure_trading_enabled(
        dchain_web3=dchain_web3,
        factory_contract=smart_account_factory,
        entry_point_contract=entry_point,
        owner=account,
        owner_private_key=private_key,
        salt=ichain_chain_id,
        session_key=session_key,
        config=user_op_config,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    print(f"  smartAccount={smart_account_status.address}")
    print(f"  deployed={smart_account_status.deployed}")
    print(f"  activeSessionKey={smart_account_status.session_key}")

    print_td_account_hint(td_account, account, smart_account_status.address)

    initial_position = get_position(symbol_manager, symbol, active_state.p_token_id)
    print(
        "Initial position:",
        f"volume={format_decimal(from_18(initial_position['volume_18']))}",
        f"cost={format_decimal(from_18(initial_position['cost_18']))}",
    )

    if close_position:
        trade_volume_18 = -initial_position["volume_18"]
        if trade_volume_18 == 0:
            raise RuntimeError("The position is already flat")
        print(f"  close_trade_volume={format_decimal(from_18(trade_volume_18))}")
    else:
        trade_volume_18 = to_18(args.trade_volume)

    validate_trade_volume(symbol, trade_volume_18)

    if args.price_limit:
        price_limit = to_decimal(args.price_limit)
    else:
        price_limit = auto_price_limit(
            args.graph_url,
            symbol_manager,
            pool,
            symbol,
            trade_volume_18,
            to_decimal(args.slippage_pct),
        )
    price_limit_18 = to_18(price_limit)
    print(f"  price_limit={format_decimal(price_limit)}")

    user_op_hash, trade_receipt = execute_engine_trade_via_user_operation(
        dchain_web3=dchain_web3,
        smart_account_address=smart_account_status.address,
        engine_contract=engine,
        entry_point_contract=entry_point,
        session_key_private_key=session_key.private_key,
        p_token_id=active_state.p_token_id,
        symbol=symbol,
        trade_volume_18=trade_volume_18,
        price_limit_18=price_limit_18,
        config=user_op_config,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    trade_tx_hash = trade_receipt.get("transactionHash") or trade_receipt.get("receipt", {}).get("transactionHash")
    print(f"dChain userOpHash: {user_op_hash}")
    if trade_tx_hash:
        print(f"dChain trade tx: {trade_tx_hash}")

    final_position = wait_for_position_change(
        symbol_manager,
        symbol,
        active_state.p_token_id,
        initial_position["volume_18"],
        trade_volume_18,
        args.timeout,
        args.poll_interval,
    )

    print("Final position:")
    print(f"  volume={format_decimal(from_18(final_position['volume_18']))}")
    print(f"  cost={format_decimal(from_18(final_position['cost_18']))}")
    print(
        f"  cumulativeFundingPerVolume={format_decimal(from_18(final_position['cumulative_funding_per_volume_18']))}"
    )
    market = find_market_by_address(pool, active_state.margin_token_address)
    save_active_ptoken_state(
        LOCAL_ACTIVE_PTOKEN_PATH,
        build_active_ptoken_state(
            account=account,
            ichain_chain_id=ichain_chain_id,
            dchain_chain_id=dchain_chain_id,
            p_token_id=active_state.p_token_id,
            pool=pool,
            zone=zone,
            market=market,
            previous_created_at=active_state.created_at,
        ),
    )


def command_remove_margin(args: argparse.Namespace) -> None:
    account, private_key = resolve_account(args, require_private_key=True)
    ichain_web3, dchain_web3, ichain_chain_id, dchain_chain_id = connect_web3_clients(args)
    pools = fetch_pool_metadatas(args.graph_url, ichain_chain_id)
    active_state = require_active_ptoken_state(account, ichain_chain_id, dchain_chain_id)
    pool, zone, selection_source = resolve_pool_from_active_state(pools, active_state)
    market = find_market_by_address(pool, active_state.margin_token_address)
    engine = get_contract(dchain_web3, pool.engine_address, "EngineImplementation.json")
    td_state = get_td_state(engine, active_state.p_token_id)

    print(f"Resolved iChain chainId={ichain_chain_id}")
    print(f"Resolved dChain chainId={dchain_chain_id}")
    print_pool_selection(pool, zone, selection_source)
    print_active_ptoken_state(active_state)
    print("Remove-margin configuration:")
    print(f"  pTokenId={active_state.p_token_id}")
    print(f"  margin_token={market.asset_symbol} ({market.asset_address})")
    if args.all:
        print("  remove_amount=ALL")
    else:
        print(f"  remove_amount={args.margin_amount}")
    smart_account_factory = get_contract(dchain_web3, pool.smart_account_factory, "EvmAccountFactory.json")
    entry_point = get_contract(dchain_web3, args.entry_point, "EntryPoint.json")
    smart_account_address = derive_smart_account_address(smart_account_factory, account, ichain_chain_id, dchain_web3)
    smart_account_status = get_smart_account_status(dchain_web3, smart_account_address)
    print("Smart-account routing:")
    print(f"  owner={account}")
    print(f"  salt={ichain_chain_id}")
    print(f"  smartAccount={smart_account_address}")
    print(f"  deployed={smart_account_status.deployed}")
    print_td_account_hint(bytes32_to_address(td_state[1]), account, smart_account_address)

    wallet_balance_before = get_wallet_token_balance(ichain_web3, market, account)
    print(f"Wallet balance before remove-margin: {format_decimal(wallet_balance_before)} {market.asset_symbol}")

    remove_amount_18 = REMOVE_MARGIN_ALL_SENTINEL if args.all else to_18(to_decimal(args.margin_amount))
    user_op_config = build_user_operation_config(args, dchain_chain_id, dchain_web3)
    user_op_hash, remove_receipt = execute_engine_remove_margin_via_user_operation(
        dchain_web3=dchain_web3,
        smart_account_address=smart_account_address,
        smart_account_deployed=smart_account_status.deployed,
        engine_contract=engine,
        entry_point_contract=entry_point,
        owner_private_key=private_key,
        p_token_id=active_state.p_token_id,
        b_token_id=td_state[2],
        remove_b_amount_18=remove_amount_18,
        config=user_op_config,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        factory_contract=smart_account_factory,
        owner=account,
        salt=ichain_chain_id,
    )
    remove_tx_hash = remove_receipt.get("transactionHash") or remove_receipt.get("receipt", {}).get("transactionHash")
    print(f"dChain userOpHash: {user_op_hash}")
    if remove_tx_hash:
        print(f"dChain remove-margin tx: {remove_tx_hash}")

    updated_td_state = get_td_state(engine, active_state.p_token_id)
    print("Updated dChain tdState:")
    print(f"  bAmount={format_decimal(from_18(int(updated_td_state[3])))}")
    print(f"  b0Amount={format_decimal(from_18(int(updated_td_state[4])))}")

    settled_balance = wait_for_wallet_balance_increase(
        ichain_web3,
        market,
        account,
        wallet_balance_before,
        args.timeout,
        args.poll_interval,
    )
    if settled_balance is None:
        print("Wallet settlement on iChain was not observed before timeout.")
        print("The remove-margin dChain step succeeded; final transfer-out is still pending relayer settlement.")
    else:
        print(f"Wallet balance after remove-margin: {format_decimal(settled_balance)} {market.asset_symbol}")
    save_active_ptoken_state(
        LOCAL_ACTIVE_PTOKEN_PATH,
        build_active_ptoken_state(
            account=account,
            ichain_chain_id=ichain_chain_id,
            dchain_chain_id=dchain_chain_id,
            p_token_id=active_state.p_token_id,
            pool=pool,
            zone=zone,
            market=market,
            previous_created_at=active_state.created_at,
        ),
    )


def build_common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ichain-rpc", default=os.getenv("ICHAIN_PROVIDER_URL", DEFAULT_ARBITRUM_SEPOLIA_RPC))
    parser.add_argument("--dchain-rpc", default=os.getenv("DCHAIN_PROVIDER_URL", DEFAULT_DCHAIN_RPC))
    parser.add_argument("--bundler-rpc", default=os.getenv("BUNDLER_RPC_URL", DEFAULT_BUNDLER_RPC))
    parser.add_argument("--graph-url", default=os.getenv("GRAPHQL_URL", DEFAULT_GRAPHQL_URL))
    parser.add_argument("--entry-point", default=os.getenv("ENTRY_POINT_ADDRESS", DEFAULT_ENTRY_POINT))
    parser.add_argument("--paymaster", default=os.getenv("PAYMASTER_ADDRESS", DEFAULT_PAYMASTER))
    parser.add_argument("--account", default=os.getenv("ACCOUNT_ADDRESS", ""))
    parser.add_argument("--private-key", default=os.getenv("ACCOUNT_PRIVATE", ""))
    parser.add_argument("--session-key-private", default=os.getenv("SESSION_KEY_PRIVATE", ""))
    parser.add_argument(
        "--zone",
        default=os.getenv("ZONE_OVERRIDE", ""),
        help="Optional manual pool override on Arbitrum Sepolia: main (Main Zone) or inno (Inno Zone)",
    )
    parser.add_argument("--gateway-address", default=os.getenv("GATEWAY_ADDRESS_OVERRIDE", ""))
    gateway_index_env = os.getenv("GATEWAY_INDEX_OVERRIDE")
    parser.add_argument("--gateway-index", type=int, default=int(gateway_index_env) if gateway_index_env else None)
    parser.add_argument(
        "--session-key-valid-seconds",
        type=int,
        default=int(os.getenv("SESSION_KEY_VALID_SECONDS", str(DEFAULT_SESSION_KEY_VALID_SECONDS))),
    )
    parser.add_argument(
        "--call-gas-limit",
        type=int,
        default=int(os.getenv("USER_OP_CALL_GAS_LIMIT", str(DEFAULT_USER_OP_CALL_GAS_LIMIT))),
    )
    parser.add_argument(
        "--verification-gas-limit",
        type=int,
        default=int(os.getenv("USER_OP_VERIFICATION_GAS_LIMIT", str(DEFAULT_USER_OP_VERIFICATION_GAS_LIMIT))),
    )
    parser.add_argument(
        "--pre-verification-gas",
        type=int,
        default=int(os.getenv("USER_OP_PRE_VERIFICATION_GAS", str(DEFAULT_USER_OP_PRE_VERIFICATION_GAS))),
    )
    parser.add_argument(
        "--max-fee-per-gas",
        type=int,
        default=int(os.getenv("USER_OP_MAX_FEE_PER_GAS", str(DEFAULT_USER_OP_MAX_FEE_PER_GAS))),
    )
    parser.add_argument(
        "--max-priority-fee-per-gas",
        type=int,
        default=int(os.getenv("USER_OP_MAX_PRIORITY_FEE_PER_GAS", str(DEFAULT_USER_OP_MAX_PRIORITY_FEE_PER_GAS))),
    )
    parser.add_argument(
        "--paymaster-verification-gas-limit",
        type=int,
        default=int(
            os.getenv(
                "USER_OP_PAYMASTER_VERIFICATION_GAS_LIMIT",
                str(DEFAULT_USER_OP_PAYMASTER_VERIFICATION_GAS_LIMIT),
            )
        ),
    )
    parser.add_argument(
        "--paymaster-post-op-gas-limit",
        type=int,
        default=int(
            os.getenv(
                "USER_OP_PAYMASTER_POST_OP_GAS_LIMIT",
                str(DEFAULT_USER_OP_PAYMASTER_POST_OP_GAS_LIMIT),
            )
        ),
    )
    parser.add_argument("--timeout", type=int, default=int(os.getenv("WAIT_TIMEOUT", "300")))
    parser.add_argument("--poll-interval", type=float, default=float(os.getenv("POLL_INTERVAL", "2")))
    return parser


def parse_args() -> argparse.Namespace:
    common = build_common_parser()
    parser = argparse.ArgumentParser(
        description="Deri Protocol V5 Pro-mode trading CLI",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  Check account status:\n"
            "    python demo.py status\n\n"
            "  Initialize the active pToken:\n"
            "    python demo.py init-p-token --zone main --margin-token USDC --margin-amount 10\n\n"
            "  Trade the active pToken:\n"
            "    python demo.py trade --symbol BTCUSD --trade-volume 0.0001\n\n"
            "  Close an existing position:\n"
            "    python demo.py close-position --symbol BTCUSD\n\n"
            "  Remove margin from the active pToken:\n"
            "    python demo.py remove-margin --margin-amount 5\n\n"
            "  List positions inside the active pToken:\n"
            "    python demo.py positions"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-p-token", parents=[common], help="Create or adopt the active demo pToken")
    init_parser.add_argument("--margin-token")
    init_parser.add_argument("--margin-amount")
    init_parser.add_argument("--symbol", help="Optional symbol hint to auto-select the pool for a new pToken")
    init_parser.add_argument("--category", default="futures")
    init_parser.add_argument("--existing-p-token-id", type=int, help="Adopt an already-created pToken as the active one")
    init_parser.add_argument("--replace-active", action="store_true", help="Replace the current active pToken state")

    subparsers.add_parser("status", parents=[common], help="Show account, smart-account, balances, and pool status")

    positions_parser = subparsers.add_parser("positions", parents=[common], help="List positions inside the active pToken")
    positions_parser.add_argument("--symbol")

    add_margin_parser = subparsers.add_parser("add-margin", parents=[common], help="Add margin to the active pToken")
    add_margin_parser.add_argument("--margin-amount", required=True)

    trade_parser = subparsers.add_parser("trade", parents=[common], help="Trade inside the active pToken on dChain")
    trade_parser.add_argument("--symbol", required=True)
    trade_parser.add_argument("--category", default="futures")
    trade_parser.add_argument("--trade-volume", required=True)
    trade_parser.add_argument("--price-limit")
    trade_parser.add_argument("--slippage-pct", default="5")

    close_parser = subparsers.add_parser("close-position", parents=[common], help="Close a position via an offsetting trade")
    close_parser.add_argument("--symbol", required=True)
    close_parser.add_argument("--category", default="futures")
    close_parser.add_argument("--price-limit")
    close_parser.add_argument("--slippage-pct", default="5")

    remove_parser = subparsers.add_parser("remove-margin", parents=[common], help="Remove margin from the active pToken")
    remove_mode = remove_parser.add_mutually_exclusive_group(required=True)
    remove_mode.add_argument("--margin-amount")
    remove_mode.add_argument("--all", action="store_true", help="Remove the maximum available margin")

    return parser.parse_args()


def main() -> None:
    load_local_env(LOCAL_ENV_PATH)
    args = parse_args()

    if args.command == "init-p-token":
        command_init_p_token(args)
        return
    if args.command == "status":
        command_status(args)
        return
    if args.command == "positions":
        command_positions(args)
        return
    if args.command == "add-margin":
        command_add_margin(args)
        return
    if args.command == "trade":
        run_trade_command(args, close_position=False)
        return
    if args.command == "close-position":
        run_trade_command(args, close_position=True)
        return
    if args.command == "remove-margin":
        command_remove_margin(args)
        return

    raise RuntimeError(f"Unsupported command {args.command}")


if __name__ == "__main__":
    main()
