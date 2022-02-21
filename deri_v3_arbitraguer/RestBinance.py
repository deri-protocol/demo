import time
import json
import hmac
import urllib
import hashlib
import requests
import threading
import logging
import traceback
from decimal import Decimal


class Rest:

    def __init__(self, url, key=None, secret=None, timeout=5):
        self.url = url
        self.key = key
        self.secret = secret
        self.timeout = timeout

        self.name = 'Rest.Binance'
        self.authen = bool(self.key and self.secret)
        self.session = requests.Session()
        self.methods = {
            'GET': self.session.get,
            'POST': self.session.post,
            'PUT': self.session.put,
            'DELETE': self.session.delete
        }


    def _sign(self, params):
        message = urllib.parse.urlencode(params)
        return hmac.new(self.secret.encode(), message.encode(), hashlib.sha256).hexdigest()


    def _http_request(self, method, path, **kwargs):
        headers = {}
        params = {key: value for key, value in kwargs.items() if value is not None}
        if self.authen:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._sign(params)
            headers = {'X-MBX-APIKEY': self.key}
        try:
            res = self.methods[method.upper()](self.url + path, params=params, headers=headers, timeout=self.timeout)
            if res.status_code // 2 == 100:
                return res.json()
            else:
                logging.error(f'({self.name}) {method} {path} ({kwargs}) invalid response: {res.text}')
        except:
            logging.error(f'({self.name}) {method} {path} ({kwargs}) error: {traceback.format_exc()}')


    def get_balance(self, currency='USDT'):
        data = self._http_request('GET', '/fapi/v2/balance')
        for item in data:
            if item['asset'] == currency:
                return Decimal(item['balance']) + Decimal(item['crossUnPnl'])


    def get_position(self, symbol='BTCUSDT'):
        data = self._http_request('GET', '/fapi/v2/positionRisk', symbol=symbol)[0]
        return {
            'symbol': data['symbol'],
            'volume': Decimal(data['positionAmt']),
            'price': Decimal(data['entryPrice'])
        }


    def place_order(self, symbol, side, amount, order_type, price=None):
        return self._http_request(
            'POST',
            '/fapi/v1/order',
            symbol=symbol,
            side=side.upper(),
            quantity=amount,
            type=order_type.upper(),
            price=price
        )




if __name__ == '__main__':
    from Preference import *

    rest = Rest(ARBITRAGUERS[0]['cefiUrl'], ARBITRAGUERS[0]['cefiKey'], ARBITRAGUERS[0]['cefiSecret'])

    # data = rest.get_balance()
    # data = rest.get_position()
    data = rest.place_order('BTCUSDT', 'sell', 0.22, 'market')

    print(data)



