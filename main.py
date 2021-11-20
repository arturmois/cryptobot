import requests
import json
import decimal
import hmac
import time
import pandas as pd
import hashlib

request_delay = 0

symbols = ['BTCUSDT', 'BNBUSDT', 'ADAUSDT', 'DOTUSDT', 'VETUSDT', 'ATOMUSDT', 'MATICUSDT', 'ETHUSDT', 'XRPUSDT']


def _get(url, params=None, headers=None) -> dict:
    """ Makes a Get Request """
    try:
        response = requests.get(url, params=params, headers=headers)
        data = json.loads(response.text)
        data['url'] = url
    except Exception as e:
        print("Exception occured when trying to access " + url)
        print(e)
        data = {'code': '-1', 'url': url, 'msg': e}
    return data


def _post(url, params=None, headers=None) -> dict:
    """ Makes a Post Request """
    try:
        response = requests.post(url, params=params, headers=headers)
        data = json.loads(response.text)
        data['url'] = url
    except Exception as e:
        print("Exception occured when trying to access " + url)
        print(e)
        data = {'code': '-1', 'url': url, 'msg': e}
    return data


class Binance:
    ORDER_STATUS_NEW = 'NEW'
    ORDER_STATUS_PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    ORDER_STATUS_FILLED = 'FILLED'
    ORDER_STATUS_CANCELED = 'CANCELED'
    ORDER_STATUS_PENDING_CANCEL = 'PENDING_CANCEL'
    ORDER_STATUS_REJECTED = 'REJECTED'
    ORDER_STATUS_EXPIRED = 'EXPIRED'

    SIDE_BUY = 'BUY'
    SIDE_SELL = 'SELL'

    ORDER_TYPE_LIMIT = 'LIMIT'
    ORDER_TYPE_MARKET = 'MARKET'
    ORDER_TYPE_STOP_LOSS = 'STOP_LOSS'
    ORDER_TYPE_STOP_LOSS_LIMIT = 'STOP_LOSS_LIMIT'
    ORDER_TYPE_TAKE_PROFIT = 'TAKE_PROFIT'
    ORDER_TYPE_TAKE_PROFIT_LIMIT = 'TAKE_PROFIT_LIMIT'
    ORDER_TYPE_LIMIT_MAKER = 'LIMIT_MAKER'

    KLINE_INTERVALS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']

    def __init__(self, filename=None):

        self.base = 'https://api.binance.com'

        self.endpoints = {
            "order": '/api/v3/order',
            "testOrder": '/api/v3/order/test',
            "allOrders": '/api/v3/allOrders',
            "klines": '/api/v3/klines',
            "exchangeInfo": '/api/v3/exchangeInfo',
            "24hrTicker": '/api/v3/ticker/24hr',
            "averagePrice": '/api/v3/avgPrice',
            "orderBook": '/api/v3/depth',
            "account": '/api/v3/account'
        }
        self.account_access = False

        if filename is None:
            return

        f = open(filename, "r")
        contents = []
        if f.mode == 'r':
            contents = f.read().split('\n')

        self.binance_keys = dict(api_key=contents[0], secret_key=contents[1])

        self.headers = {"X-MBX-APIKEY": self.binance_keys['api_key']}

        self.account_access = True

    def sign_request(self, params: dict):
        """ Signs the request to the Binance API """

        query_string = '&'.join(["{}={}".format(d, params[d]) for d in params])
        signature = hmac.new(
            self.binance_keys['secret_key'].encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256
        )
        params['signature'] = signature.hexdigest()

    @classmethod
    def float_to_string(cls, f: float):
        """ Converts the given float to a string,
        without resorting to the scientific notation """

        ctx = decimal.Context()
        ctx.prec = 12
        d1 = ctx.create_decimal(repr(f))
        return format(d1, 'f')

    def get_account_data(self) -> dict:
        """ Gets Balances & Account Data """

        url = self.base + self.endpoints["account"]

        params = {
            'recvWindow': 6000,
            'timestamp': int(round(time.time() * 1000)) + request_delay
        }
        self.sign_request(params)

        return _get(url, params, self.headers)

    def get_trading_symbols(self, quoteassets: list = None):
        """ Gets All symbols which are tradable (currently) """
        url = self.base + self.endpoints["exchangeInfo"]
        data = _get(url)
        if data.__contains__('code'):
            return []

        symbols_list = []
        for pair in data['symbols']:
            if pair['status'] == 'TRADING':
                if quoteassets is not None and pair['quoteAsset'] in quoteassets:
                    symbols_list.append(pair['symbol'])

        return symbols_list

    def get_24hr_ticker(self, symbol: str):
        url = self.base + self.endpoints['24hrTicker'] + "?symbol=" + symbol
        return _get(url)

    def get_symbol_klines(self, symbol: str, interval: str, limit: int = 1000, end_time=False):
        """
        Gets trading data for one symbol

        Parameters
        --
            symbol str:        The symbol for which to get the trading data

            interval str:      The interval on which to get the trading data
                minutes      '1m' '3m' '5m' '15m' '30m'
                hours        '1h' '2h' '4h' '6h' '8h' '12h'
                days         '1d' '3d'
                weeks        '1w'
                months       '1M;
        """

        if limit > 1000:
            return self.get_symbol_klines_extra(symbol, interval, limit, end_time)

        params = '?&symbol=' + symbol + '&interval=' + interval + '&limit=' + str(limit)
        if end_time:
            params = params + '&endTime=' + str(int(end_time))

        url = self.base + self.endpoints['klines'] + params

        # download data
        data = requests.get(url)
        dictionary = json.loads(data.text)

        # put in dataframe and clean-up
        df = pd.DataFrame.from_dict(dictionary)
        df = df.drop(range(6, 12), axis=1)

        # rename columns
        col_names = ['time', 'open', 'high', 'low', 'close', 'volume']
        df.columns = col_names

        # transform values from strings to floats
        for col in col_names:
            df[col] = df[col].astype(float)

        df['date'] = pd.to_datetime(df['time'] * 1000000, infer_datetime_format=True)

        return df

    def get_symbol_klines_extra(self, symbol: str, interval: str, limit: int = 1000, end_time=False):
        # Basicall, we will be calling the GetSymbolKlines as many times as we need
        # in order to get all the historical data required (based on the limit parameter)
        # and we'll be merging the results into one long dataframe.

        repeat_rounds = 0
        if limit > 1000:
            repeat_rounds = int(limit / 1000)
        initial_limit = limit % 1000
        if initial_limit == 0:
            initial_limit = 1000
        # First, we get the last initial_limit candles, starting at end_time and going
        # backwards (or starting in the present moment, if end_time is False)
        df = self.get_symbol_klines(symbol, interval, limit=initial_limit, end_time=end_time)
        while repeat_rounds > 0:
            # Then, for every other 1000 candles, we get them, but starting at the beginning
            # of the previously received candles.
            df2 = self.get_symbol_klines(symbol, interval, limit=1000, end_time=df['time'][0])
            df = df2.append(df, ignore_index=True)
            repeat_rounds = repeat_rounds - 1

        return df

    def place_order(self, symbol: str, side: str, tpe: str, quantity: float = 0, price: float = 0, test: bool = True):
        """
        Places an order on Binance
        Parameters
        --
            symbol str:        The symbol for which to get the trading data
            side str:          The side of the order 'BUY' or 'SELL'
            type str:          The type, 'LIMIT', 'MARKET', 'STOP_LOSS'
            quantity float:

        """

        params = {
            'symbol': symbol,
            'side': side,  # BUY or SELL
            'type': tpe,  # MARKET, LIMIT, STOP LOSS etc
            'quoteOrderQty': quantity,
            'recvWindow': 5000,
            'timestamp': int(round(time.time() * 1000)) + request_delay
        }

        if type != 'MARKET':
            params['timeInForce'] = 'GTC'
            params['price'] = Binance.float_to_string(price)

        self.sign_request(params)

        if test:
            url = self.base + self.endpoints['testOrder']
        else:
            url = self.base + self.endpoints['order']

        return _post(url, params=params, headers=self.headers)

    def market_order(self, symbol: str, side: str, quantity: float = 0):
        params = {
            'symbol': symbol,
            'side': side,  # BUY or SELL
            'type': 'MARKET',  # MARKET, LIMIT, STOP LOSS etc
            'quoteOrderQty': quantity,
            'recvWindow': 5000,
            'timestamp': int(round(time.time() * 1000)) + request_delay
        }

        self.sign_request(params)

        url = self.base + self.endpoints['order']

        return _post(url, params=params, headers=self.headers)

    def get_account_balances(self):
        url = self.base + self.endpoints["account"]

        params = {
            'recvWindow': 6000,
            'timestamp': int(round(time.time() * 1000)) + request_delay
        }
        self.sign_request(params)

        spot_account = _get(url, params, self.headers)
        account_assets = dict()
        balance_usd = 0
        cont = 1
        for balance in spot_account['balances']:
            if balance['asset'] == 'USDT':
                account_assets['USDT'] = round(float(balance['free']), 2)
                balance_usd += float(balance['free'])

            if balance['asset'] not in ['NFT', 'USDT', 'BRL']:
                if float(balance['free']) > 0:
                    usd_price = _get(
                        self.base + self.endpoints['24hrTicker'] + "?symbol=" + balance['asset'] + 'USDT'
                    )['lastPrice']
                    account_assets[balance['asset'] + 'USDT'] = round(float(usd_price) * float(balance['free']), 2)
                    balance_usd += float(usd_price) * float(balance['free'])
            cont += 1
        account_assets['BALANCE'] = round(balance_usd, 2)
        return account_assets


def main():

    exchange = Binance('credentials.txt')
    balances = exchange.get_account_balances()
    excel = pd.read_excel('wallet.xlsx')
    wallet = {}
    for x in range(len(excel['assets'])):
        wallet[excel['assets'][x]] = excel['%'][x]

    for asset in wallet:
        if asset not in ['USDT']:
            if asset in balances:
                if balances[asset] > ((wallet[asset] / 100) * balances['BALANCE']) + 10:
                    try:
                        r = exchange.market_order(
                            asset,
                            'SELL',
                            round(balances[asset] - (wallet[asset] / 100) * balances['BALANCE'], 2)
                        )
                        print(r)
                    except Exception as e:
                        print(e)

                if balances[asset] < ((wallet[asset] / 100) * balances['BALANCE']) - 10:
                    try:
                        r = exchange.market_order(
                            asset,
                            'BUY',
                            round((wallet[asset] / 100) * balances['BALANCE'] - balances[asset], 2)
                        )
                        print(r)
                    except Exception as e:
                        print(e)
            else:
                try:
                    r = exchange.market_order(
                        asset,
                        'BUY',
                        round(wallet[asset] / 100 * balances['BALANCE'], 2)

                    )
                    print(r)
                except Exception as e:
                    print(e)


if __name__ == '__main__':
    main()
