import json
import requests
from web3 import Web3

ONE = 10**18
MAX = 10**256 - 1

PROVIDER_URL = ''
ACCOUNT_ADDRESS = ''
ACCOUNT_PRIVATE = ''
BASE_TOKEN_ADDRESS = ''
PERPETUAL_POOL_ADDRESS = ''
ORACLE_URL = 'https://oracle.deri.finance/price/?symbol=BTCUSD'

web3 = Web3(Web3.HTTPProvider(PROVIDER_URL))
session = requests.session()


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


def get_signature():
    data = session.get(ORACLE_URL)
    data = data.json()
    return (
        int(data['timestamp']),
        int(data['price']),
        Web3.toInt(hexstr=data['v']),
        data['r'],
        data['s']
    )


# approve pool for spending your base token
def approve():
    contract = get_contract(BASE_TOKEN_ADDRESS, 'ERC20')
    receipt = transact(contract, 'approve', (PERPETUAL_POOL_ADDRESS, MAX))
    return receipt


def add_liquidity(amount):
    contract = get_contract(PERPETUAL_POOL_ADDRESS, 'PerpetualPool')
    timestamp, price, v, r, s = get_signature()
    receipt = transact(contract, 'addLiquidity', (int(amount * ONE), timestamp, price, v, r, s))
    return receipt


def remove_liquidity(lshares):
    contract = get_contract(PERPETUAL_POOL_ADDRESS, 'PerpetualPool')
    timestamp, price, v, r, s = get_signature()
    receipt = transact(contract, 'removeLiquidity', (int(lShares * ONE), timestamp, price, v, r, s))
    return receipt


def deposit_margin(amount):
    contract = get_contract(PERPETUAL_POOL_ADDRESS, 'PerpetualPool')
    timestamp, price, v, r, s = get_signature()
    receipt = transact(contract, 'depositMargin', (int(amount * ONE), timestamp, price, v, r, s))
    return receipt


def withdraw_margin(amount):
    contract = get_contract(PERPETUAL_POOL_ADDRESS, 'PerpetualPool')
    timestamp, price, v, r, s = get_signature()
    receipt = transact(contract, 'withdrawMargin', (int(amount * ONE), timestamp, price, v, r, s))
    return receipt


def trade(volume):
    contract = get_contract(PERPETUAL_POOL_ADDRESS, 'PerpetualPool')
    timestamp, price, v, r, s = get_signature()
    receipt = transact(contract, 'trade', (int(volume * ONE), timestamp, price, v, r, s))
    return receipt


def liquidate(account):
    contract = get_contract(PERPETUAL_POOL_ADDRESS, 'PerpetualPool')
    timestamp, price, v, r, s = get_signature()
    receipt = transact(contract, 'liquidate', (account, timestamp, price, v, r, s))
    return receipt

