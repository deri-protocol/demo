import json
from web3 import Web3

ONE = 10**18
MAX = 10**256 - 1

PROVIDER_URL = ''
ACCOUNT_ADDRESS = ''
ACCOUNT_PRIVATE = ''
BASE_TOKEN_ADDRESS = ''
POOL_ADDRESS = ''

web3 = Web3(Web3.HTTPProvider(PROVIDER_URL))


def get_abi(contract_name):
    with open(f'abis/{contract_name}.json') as file:
        data = json.load(file)
    return data['abi']


def get_contract(address, contract_name):
    return web3.eth.contract(address=address, abi=get_abi(contract_name))


def transact(contract, function_name, params=()):
    nonce = web3.eth.getTransactionCount(ACCOUNT_ADDRESS)
    gas = contract.functions[function_name](*params).estimateGas({'from': ACCOUNT_ADDRESS})
    tx = contract.functions[function_name](*params).buildTransaction({
        'nonce': nonce,
        'from': ACCOUNT_ADDRESS,
        'gas': int(gas * 1.2)
    })
    signed_tx = web3.eth.ACCOUNT_ADDRESS.signTransaction(tx, ACCOUNT_PRIVATE)
    tx_hash = web3.eth.sendRawTransaction(signed_tx.rawTransaction)
    receipt = web3.eth.waitForTransactionReceipt(tx_hash)
    return receipt


# approve pool for spending your base token
def approve():
    contract = get_contract(BASE_TOKEN_ADDRESS, 'ERC20')
    receipt = transact(contract, 'approve', (POOL_ADDRESS, MAX))
    return receipt


# if no oracleSignatures are required, pass [] as the third parameter
# if there are oracleSignatures, pass [[oracleSymbolId, timestamp, value, v, r, s], ...] as the third parameter
# oracleSignatures can be obtained from our oracle servers
def add_liquidity(b_token_address, amount):
    contract = get_contract(POOL_ADDRESS, 'PoolImplementation')
    receipt = transact(contract, 'addLiquidity', (b_token_address, int(amount * ONE), []))
    return receipt


def remove_liquidity(b_token_address, amount):
    contract = get_contract(POOL_ADDRESS, 'PoolImplementation')
    receipt = transact(contract, 'removeLiquidity', (b_token_address, int(amount * ONE), []))
    return receipt


def add_margin(b_token_address, amount):
    contract = get_contract(POOL_ADDRESS, 'PoolImplementation')
    receipt = transact(contract, 'addMargin', (b_token_address, int(amount * ONE), []))
    return receipt


def remove_margin(b_token_address, amount):
    contract = get_contract(POOL_ADDRESS, 'PoolImplementation')
    receipt = transact(contract, 'removeMargin', (b_token_address, int(amount * ONE), []))
    return receipt


# symbol is the trading symbol, e.g. 'BTCUSD'
def trade(symbol, volume):
    contract = get_contract(POOL_ADDRESS, 'PoolImplementation')
    receipt = transact(contract, 'trade', (symbol, int(volume * ONE), []))
    return receipt


def liquidate(pTokenId):
    contract = get_contract(POOL_ADDRESS, 'PoolImplementation')
    receipt = transact(contract, 'liquidate', (pTokenId,, []))
    return receipt
