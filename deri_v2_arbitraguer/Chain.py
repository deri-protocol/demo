import time
import json
import random
from web3 import Web3
from web3.middleware import geth_poa_middleware, local_filter_middleware
from Preference import *


ABIS = {}


def getWeb3(network):
    web3 = Web3(Web3.HTTPProvider(random.choice(RPCS[network])))
    if 'bsc' in network or 'heco' in network:
        web3.middleware_onion.inject(geth_poa_middleware, layer=0)
        web3.middleware_onion.add(local_filter_middleware)
    web3.network = network
    return web3


def getAbi(abiName):
    global ABIS
    if abiName in ABIS: return ABIS[abiName]
    with open(f'{DIR_ABIS}/{abiName}.json') as file:
        interface = json.load(file)
    ABIS[abiName] = interface['abi']
    return ABIS[abiName]


def getContract(network, address, abiName):
    web3 = getWeb3(network)
    contract = web3.eth.contract(address=address, abi=getAbi(abiName))
    return contract


def call(network, address, abiName, functionName, params=None):
    contract = getContract(network, address, abiName)
    if params is None: params = []
    return contract.functions[functionName](*params).call()


def transact(network, address, abiName, functionName, params, account, private):
    contract = getContract(network, address, abiName)
    tx = contract.functions[functionName](*params).buildTransaction({
        'nonce': contract.web3.eth.getTransactionCount(account),
        'from': account,
        'gas': contract.functions[functionName](*params).estimateGas({'from': account}) * 3 // 2
    })
    signedTx = contract.web3.eth.account.signTransaction(tx, private)
    txHash = contract.web3.eth.sendRawTransaction(signedTx.rawTransaction)
    receipt = contract.web3.eth.waitForTransactionReceipt(txHash)
    return receipt
