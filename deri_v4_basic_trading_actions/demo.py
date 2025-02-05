import json
import time
from web3 import Web3
import eth_abi
import hexbytes

ONE = 10**18
MAX = 10**256 - 1
ETH_ADDRESS = "0x0000000000000000000000000000000000000001"

# RPC URL for connecting to the ichain (e.g. https://arb1.arbitrum.io/rpc)
ICHAIN_PROVIDER_URL = ""

# RPC URL for connecting to the dchain
DCHAIN_PROVIDER_URL = "https://rpc-dchain.deri.io"

# Address of the account used for transactions
ACCOUNT_ADDRESS = ""

# Private key for signing transactions from the account
ACCOUNT_PRIVATE = ""

# Address of the base token used as margin
# Could be ETH_ADDRESS(0x0000000000000000000000000000000000000001) or another ERC20 token supported
# e.g.
# USDC token address of arbitrium: 0xaf88d065e77c8cc2239327c5edb3a432268e5831
# USDC token address of linea: 0x176211869ca2b568f2a7d4ee941e073a821ee1ff
# USDC token address of base: 0x833589fcd6edb6e08f4c7c32d4f71b54bda02913
BASE_TOKEN_ADDRESS = ""

# Address of the Gateway contract
# arbitrium: 0x7C4a640461427C310a710D367C2Ba8C535A7Ef81
# linea: 0xe840Bb03fE58540841e6eBee94264d5317B88866
# base: 0xd4E08C940dDeC162c2D8f3034c75c3e08f1f6032
# more chains: https://docs.deri.io/library/list-of-smart-contracts
GATEWAY_ADDRESS = ""

# Address of the Symbol Manager contract
# main: 0x5a98af1a854f365f1602696c3f5469a7950063fa
# inno: 0x9538e4ff455f62d25188aeb05dc4c12dcb3df4fa
SYMBOL_MANAGER_ADDRESS = ""

web3 = Web3(Web3.HTTPProvider(ICHAIN_PROVIDER_URL))


def get_abi(contract_name):
    with open(f"abis/{contract_name}.json") as file:
        data = json.load(file)
    return data["abi"] if isinstance(data, dict) else data


def get_contract(address, contract_name):
    return web3.eth.contract(address=address, abi=get_abi(contract_name))


def transact(contract, function_name, params=(), value=0):
    account_address = web3.to_checksum_address(ACCOUNT_ADDRESS)
    nonce = web3.eth.get_transaction_count(account_address)
    tx = contract.functions[function_name](*params).build_transaction(
        {"nonce": nonce, "from": account_address, "value": value}
    )
    signed_tx = web3.eth.account.sign_transaction(tx, ACCOUNT_PRIVATE)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    return receipt


def call(contract, function_name, params=None):
    if params is None:
        params = []
    return contract.functions[function_name](*params).call()


_, _, REMOVE_MARGIN_EXECUTION_FEE, TRADE_EXECUTION_FEE, _ = call(
    get_contract(GATEWAY_ADDRESS, "GatewayImplementation"), "getExecutionFees"
)


# approve gateway for spending your base token
def approve():
    if BASE_TOKEN_ADDRESS != ETH_ADDRESS:
        contract = get_contract(BASE_TOKEN_ADDRESS, "ERC20")
        receipt = transact(contract, "approve", (GATEWAY_ADDRESS, MAX))
        return receipt


def request_add_margin(p_token_id, b_token_address, amount):
    contract = get_contract(GATEWAY_ADDRESS, "GatewayImplementation")
    value = 0 if b_token_address != ETH_ADDRESS else int(amount * ONE)
    receipt = transact(
        contract,
        "requestAddMargin",
        (p_token_id, b_token_address, int(amount * ONE), False),
        value,
    )
    return receipt


def request_remove_margin(p_token_id, b_token_address, amount):
    contract = get_contract(GATEWAY_ADDRESS, "GatewayImplementation")
    receipt = transact(
        contract,
        "requestRemoveMargin",
        (p_token_id, b_token_address, int(amount * ONE)),
        REMOVE_MARGIN_EXECUTION_FEE,
    )
    return receipt


def request_trade(p_token_id, symbol_id, trade_volume, price_limit):
    contract = get_contract(GATEWAY_ADDRESS, "GatewayImplementation")
    receipt = transact(
        contract,
        "requestTrade",
        (p_token_id, symbol_id, [int(trade_volume * ONE), int(price_limit * ONE)]),
        TRADE_EXECUTION_FEE,
    )
    return receipt


def check_position(symbol_id, p_token_id):
    web3_dchain = Web3(Web3.HTTPProvider(DCHAIN_PROVIDER_URL))
    contract = web3_dchain.eth.contract(
        address=SYMBOL_MANAGER_ADDRESS, abi=get_abi("SymbolManagerImplementation")
    )
    res = call(contract, "getPosition", (symbol_id, p_token_id))
    return int(res[0].hex(), 16)


def decode(types, data):
    decoded = eth_abi.decode(types, hexbytes.HexBytes(data))
    return decoded


def get_symbol_id(symbol, category):
    symbol_bytes = symbol.encode("utf-8").ljust(32, b"\x00")
    category_bytes = category.to_bytes(32, "big")
    symbol_id = bytes(x | y for x, y in zip(symbol_bytes, category_bytes))
    return symbol_id


def get_min_trade_volume(symbol_id):
    web3_dchain = Web3(Web3.HTTPProvider(DCHAIN_PROVIDER_URL))
    contract = web3_dchain.eth.contract(
        address=SYMBOL_MANAGER_ADDRESS, abi=get_abi("SymbolManagerImplementation")
    )
    res = call(contract, "getState", (symbol_id,))
    return int(res[2].hex(), 16)


def get_p_token_id(receipt):
    logs = receipt.logs
    for log in logs:
        if log.topics == [
            web3.keccak(text="FinishAddMargin(uint256,uint256,address,uint256)")
        ]:
            _, p_token_id, _, _ = decode(
                ["uint256", "uint256", "address", "uint256"], log.data
            )
            return p_token_id


if __name__ == "__main__":
    # example of trading BTCUSD
    # Approve the Gateway contract to spend the base token on behalf of the account
    approve()

    # Add margin to open or increase a position. Here, 0 is used for a new position
    # BASE_TOKEN_ADDRESS specifies which token is used for margin (could be ETH or another token)
    # 0.001 is the amount of margin added
    receipt = request_add_margin(0, BASE_TOKEN_ADDRESS, 0.001)

    # Extract the position token ID from the transaction receipt
    p_token_id = get_p_token_id(receipt)

    # Get the unique ID for the trading symbol
    # futures: category=1, option: category=2, power: category=3
    # e.g. BTCUSD in category 1, BTCUSD-11000-C in category 2, BTC^2 in category 3
    symbol_id = get_symbol_id("BTCUSD", 1)

    min_trade_volume = get_min_trade_volume(symbol_id)
    # Set the trade volume. Here, 0.0001 is used, which needs to be checked against the minimum volume
    trade_volume = 0.0001

    # Ensure that the trade volume is greater than the minimum allowed volume
    assert (
        trade_volume * ONE > min_trade_volume
    ), "Trade volume is below the minimum allowed"

    # Ensure that the trade volume is an integer multiple of min_trade_volume
    assert (
        trade_volume * ONE % min_trade_volume == 0
    ), "Trade volume must be an integer multiple of min_trade_volume"

    # Set the price limit for the trade
    # If going long (buying), set price_limit higher than the current market price
    # If going short (selling), set price_limit lower than the current market price
    # The exact value depends on your risk tolerance and market analysis, with suggestions of being 3% or 5% away from the market price.
    price_limit = 110000
    pre_position = check_position(symbol_id, p_token_id)
    request_trade(p_token_id, symbol_id, trade_volume, price_limit)
    while check_position(symbol_id, p_token_id) != pre_position + int(
        trade_volume * ONE
    ):
        time.sleep(1)
    print(f"Traded: {trade_volume} BTCUSD")
