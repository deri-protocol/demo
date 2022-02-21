import time
import logging
import requests
import traceback
from web3 import Web3
from decimal import Decimal
from Preference import *
import Chain
import RestBinance


class ArbitraguerV3:

    def __init__(self, details):
        self.defiNetwork = details['defiNetwork']
        self.defiPoolAddress = details['defiPoolAddress']
        self.defiAccount = details['defiAccount']
        self.defiPrivate = details['defiPrivate']
        self.defiSymbol = details['defiSymbol']
        self.defiMinVolume = details['defiMinVolume']
        self.defiMaxVolume = details['defiMaxVolume']

        self.symbolManagerAddress = Chain.call(self.defiNetwork, self.defiPoolAddress, 'PoolImplementation', 'symbolManager', [])
        self.symbolAddress = Chain.call(
            self.defiNetwork, self.symbolManagerAddress, 'SymbolManagerImplementation', 'symbols', [Chain.getId(self.defiSymbol)]
        )
        self.pTokenAddress = Chain.call(self.defiNetwork, self.defiPoolAddress, 'PoolImplementation', 'pToken', [])
        self.pTokenId = Chain.call(self.defiNetwork, self.pTokenAddress, 'DToken', 'getTokenIdOf', [self.defiAccount])

        self.cefiExchange = details['cefiExchange']
        self.cefiUrl = details['cefiUrl']
        self.cefiKey = details['cefiKey']
        self.cefiSecret = details['cefiSecret']
        self.cefiSymbol = details['cefiSymbol']
        self.cefiMiltiplier = details['cefiMiltiplier']
        self.cefiMinVolume = details['cefiMinVolume']

        if self.cefiExchange == 'Binance':
            self.rest = RestBinance.Rest(self.cefiUrl, self.cefiKey, self.cefiSecret)
        else:
            raise ValueError(f'Unsopported cefi exchange: {self.cefiExchange}')

        self.update_defi_symbol_state()
        self.update_defi_margin()
        self.update_defi_position()
        self.update_cefi_position()


    def update_defi_symbol_state(self):
        price = Chain.call(self.defiNetwork, self.symbolAddress, 'SymbolImplementationFutures', 'indexPrice', [])
        cumulativeFundingPerVolume = Chain.call(self.defiNetwork, self.symbolAddress, 'SymbolImplementationFutures', 'cumulativeFundingPerVolume', [])
        netVolume = Chain.call(self.defiNetwork, self.symbolAddress, 'SymbolImplementationFutures', 'netVolume', [])
        netCost = Chain.call(self.defiNetwork, self.symbolAddress, 'SymbolImplementationFutures', 'netCost', [])
        self.defi_symbol_state = {
            'price': Decimal(price) / ONE,
            'cumulativeFundingPerVolume': Decimal(cumulativeFundingPerVolume) / ONE,
            'netVolume': Decimal(netVolume) / ONE,
            'netCost': Decimal(netCost) / ONE
        }


    def update_defi_margin(self):
        vault, amountB0 = Chain.call(self.defiNetwork, self.defiPoolAddress, 'PoolImplementation', 'tdInfos', [self.pTokenId])
        vaultLiquidity = Chain.call(self.defiNetwork, vault, 'VaultImplementation', 'getVaultLiquidity', [])
        self.defi_margin = (Decimal(vaultLiquidity) + Decimal(amountB0)) / ONE


    def update_defi_position(self):
        volume, cost, lastCumulativeFundingPerVolume = Chain.call(
            self.defiNetwork, self.symbolAddress, 'SymbolImplementationFutures', 'positions', [self.pTokenId]
        )
        self.defi_position = {
            'volume': Decimal(volume) / ONE,
            'cost': Decimal(cost) / ONE,
            'lastCumulativeFundingPerVolume': Decimal(lastCumulativeFundingPerVolume) / ONE
        }


    def update_cefi_position(self):
        self.cefi_position = self.rest.get_position(symbol=self.cefiSymbol)


    def get_defi_pnl(self):
        pnl = self.defi_position['volume'] * self.defi_symbol_state['price'] - self.defi_position['cost']
        funding = (self.defi_symbol_state['cumulativeFundingPerVolume'] - self.defi_position['lastCumulativeFundingPerVolume']) * self.defi_position['volume']
        return pnl - funding


    def get_cefi_dynamic_equity(self):
        return self.rest.get_balance()


    def check_defi_position(self):
        pool_volume = self.defi_symbol_state['netVolume']
        defi_volume = self.defi_position['volume']
        target = -(pool_volume - defi_volume) / 2
        target = min(target, self.defiMaxVolume) if target >= 0 else max(target, -self.defiMaxVolume)
        if target == 0:
            delta = -defi_volume
        elif target * defi_volume >= 0:
            delta = (target - defi_volume) // self.defiMinVolume * self.defiMinVolume
        else:
            delta = target // self.defiMinVolume * self.defiMinVolume - defi_volume
        if delta == 0 and pool_volume * defi_volume >= 0:
            delta = -defi_volume
        logging.info(f'(Defi) PoolNetVolume: {pool_volume}, HedgeTargetVolume: {target}, ArbitraguerVolume: {defi_volume}, Delta: {delta}')

        if delta != 0:
            price = self.defi_symbol_state['price']
            priceLimit = int(price * 1.1 * ONE) if delta > 0 else int(price * 0.9 * ONE)
            oracleSignatures = []
            receipt = Chain.transact(self.defiNetwork, self.defiPoolAddress, 'PoolImplementation', 'trade',
                                     [self.defiSymbol, int(delta * ONE), priceLimit, oracleSignatures], self.defiAccount, self.defiPrivate)
            logging.info(f'       Receipt: ({receipt.transactionHash.hex()}, {receipt.status})')
            self.update_defi_margin()
            self.update_defi_position()
            logging.info(f'       ArbitraguerVolume: {defi_volume} => {self.defi_position["volume"]}')


    def check_cefi_position(self):
        defi_volume = self.defi_position['volume']
        cefi_volume = self.cefi_position['volume']
        target = -defi_volume / self.cefiMiltiplier // self.cefiMinVolume * self.cefiMinVolume
        delta = target - cefi_volume
        logging.info(f'(Cefi) DefiVolume: {defi_volume}, CefiTargetVolume: {target}, CefiVolume: {cefi_volume}, Delta: {delta}')

        if delta != 0:
            self.rest.place_order(self.cefiSymbol, 'buy' if delta > 0 else 'sell', str(abs(delta)), 'market')
            self.update_cefi_position()
            logging.info(f'       CefiVolume: {cefi_volume} => {self.cefi_position["volume"]}')


    def check(self):
        logging.info(f'====> Check {self.defiSymbol}.{self.cefiSymbol}')
        self.update_defi_symbol_state()
        self.check_defi_position()
        self.check_cefi_position()








if __name__ == '__main__':

    arbitraguer = ArbitraguerV3(ARBITRAGUERS[0])
    print(arbitraguer.__dict__)

    # print(arbitraguer.get_defi_pnl())
    print(arbitraguer.get_cefi_dynamic_equity())



