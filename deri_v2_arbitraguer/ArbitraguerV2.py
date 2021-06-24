import time
import logging
import requests
import traceback
from web3 import Web3
from decimal import Decimal
from Preference import *
import Chain
import RestBinance


class ArbitraguerV2:

    def __init__(self, details):
        self.defiNetwork = details['defiNetwork']
        self.defiPoolAddress = details['defiPoolAddress']
        self.defiPoolRouterAddress = details['defiPoolRouterAddress']
        self.defiPoolPTokenAddress = details['defiPoolPTokenAddress']
        self.defiAccount = details['defiAccount']
        self.defiPrivate = details['defiPrivate']
        self.defiSymbolId = details['defiSymbolId']
        self.defiMultiplier = details['defiMultiplier']
        self.defiMinVolume = details['defiMinVolume']
        self.defiMaxVolume = details['defiMaxVolume']

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
        _, _, _, _, _, price, cumulativeFundingRate, tradersNetVolume, tradersNetCost = Chain.call(
            self.defiNetwork, self.defiPoolAddress, 'PerpetualPoolV2', 'getSymbol', [self.defiSymbolId]
        )
        self.defi_symbol_state = {
            'price': Decimal(price) / ONE,
            'cumulativeFundingRate': Decimal(cumulativeFundingRate) / ONE,
            'tradersNetVolume': Decimal(tradersNetVolume) / ONE,
            'tradersNetCost': Decimal(tradersNetCost) / ONE
        }


    def update_defi_margin(self):
        margin = Chain.call(self.defiNetwork, self.defiPoolPTokenAddress, 'PTokenV2', 'getMargin', [self.defiAccount, 0])
        self.defi_margin = Decimal(margin) / ONE


    def update_defi_position(self):
        volume, cost, lastCumulativeFundingRate = Chain.call(
            self.defiNetwork, self.defiPoolPTokenAddress, 'PTokenV2', 'getPosition', [self.defiAccount, self.defiSymbolId]
        )
        self.defi_position = {
            'volume': Decimal(volume) / ONE,
            'cost': Decimal(cost) / ONE,
            'lastCumulativeFundingRate': Decimal(lastCumulativeFundingRate) / ONE
        }


    def update_cefi_position(self):
        self.cefi_position = self.rest.get_position(symbol=self.cefiSymbol)


    def get_defi_pnl(self):
        pnl = self.defi_position['volume'] * self.defi_symbol_state['price'] * self.defiMultiplier - self.defi_position['cost']
        funding = (self.defi_symbol_state['cumulativeFundingRate'] - self.defi_position['lastCumulativeFundingRate']) * self.defi_position['volume']
        return pnl - funding


    def get_cefi_dynamic_equity(self):
        return self.rest.get_balance()


    def check_defi_position(self):
        pool_volume = self.defi_symbol_state['tradersNetVolume']
        defi_volume = self.defi_position['volume']
        target = -(pool_volume - defi_volume) // 2
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
            receipt = Chain.transact(self.defiNetwork, self.defiPoolRouterAddress, 'PerpetualPoolRouterV2', 'trade',
                                     [self.defiSymbolId, int(delta) * ONE], self.defiAccount, self.defiPrivate)
            logging.info(f'       Receipt: ({receipt.transactionHash.hex()}, {receipt.status})')
            self.update_defi_margin()
            self.update_defi_position()
            logging.info(f'       ArbitraguerVolume: {defi_volume} => {self.defi_position["volume"]}')


    def check_cefi_position(self):
        defi_volume = self.defi_position['volume']
        cefi_volume = self.cefi_position['volume']
        target = -defi_volume * self.defiMultiplier / self.cefiMiltiplier // self.cefiMinVolume * self.cefiMinVolume
        delta = target - cefi_volume
        logging.info(f'(Cefi) DefiVolume: {defi_volume}, CefiTargetVolume: {target}, CefiVolume: {cefi_volume}, Delta: {delta}')

        if delta != 0:
            self.rest.place_order(self.cefiSymbol, 'buy' if delta > 0 else 'sell', str(abs(delta)), 'market')
            self.update_cefi_position()
            logging.info(f'       CefiVolume: {cefi_volume} => {self.cefi_position["volume"]}')


    def check(self):
        logging.info(f'====> Check {self.defiSymbolId}.{self.cefiSymbol}')
        self.update_defi_symbol_state()
        self.check_defi_position()
        self.check_cefi_position()








if __name__ == '__main__':

    arbitraguer = ArbitraguerV2(ARBITRAGUERS_V2[0])
    print(arbitraguer.__dict__)

    # print(arbitraguer.get_defi_pnl())
    print(arbitraguer.get_cefi_dynamic_equity())



