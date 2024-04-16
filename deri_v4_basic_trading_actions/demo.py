import json
import time
from web3 import Web3
import eth_abi
import hexbytes

ONE = 10**18
MAX = 10**256 - 1
ETH_ADDRESS = "0x0000000000000000000000000000000000000001"

ICHAIN_PROVIDER_URL = ""
DCHAIN_PROVIDER_URL = ""
ACCOUNT_ADDRESS = ""
ACCOUNT_PRIVATE = ""
BASE_TOKEN_ADDRESS = ""
GATEWAY_ADDRESS = ""
SYMBOL_MANAGER_ADDRESS = ""
TRADE_EXECUTION_FEE =
REMOVE_MARGIN_EXECUTION_FEE =

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
    approve()
    receipt = request_add_margin(0, BASE_TOKEN_ADDRESS, 0.001)
    p_token_id = get_p_token_id(receipt)
    symbol_id = get_symbol_id("BTCUSD", 1)
    trade_volume = 0.0001
    price_limit = 73000
    pre_position = check_position(symbol_id, p_token_id)
    request_trade(p_token_id, symbol_id, trade_volume, price_limit)
    while check_position(symbol_id, p_token_id) != pre_position + int(
        trade_volume * ONE
    ):
        time.sleep(1)
    print(f"Traded: {trade_volume} BTCUSD")
