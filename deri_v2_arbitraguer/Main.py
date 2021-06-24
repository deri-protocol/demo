import time
import traceback
from Preference import *
from ArbitraguerV2 import ArbitraguerV2


if __name__ == '__main__':

    arbitraguers = [ArbitraguerV2(details) for details in ARBITRAGUERS_V2]

    while True:

        try:
            defi_dynamic_equity = Decimal(0)
            cefi_dynamic_equity = Decimal(0)

            for arbitraguer in arbitraguers:
                arbitraguer.check()
                defi_dynamic_equity += arbitraguer.get_defi_pnl()

            defi_dynamic_equity += arbitraguers[0].defi_margin
            cefi_dynamic_equity = arbitraguers[0].get_cefi_dynamic_equity()

            logging.info(f'====> Dynamic equity: Defi: {defi_dynamic_equity:.3f}, Cefi: {cefi_dynamic_equity:.3f}, Total: {defi_dynamic_equity + cefi_dynamic_equity:.3f}')

        except Exception as e:
            logging.error(f'Arbitraguer error: {traceback.format_exc()}')

        time.sleep(60)
