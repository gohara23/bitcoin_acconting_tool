import requests
import cbpro
import time
import datetime as dt
from dotenv import load_dotenv
import os
from pprint import pprint
import json
from robin_stocks import robinhood as rh
import pyotp
import pandas as pd
from dataclasses import dataclass, field
from typing import List
from abc import ABC, abstractmethod
import operator
from copy import copy


@dataclass
class Transaction:
    symbol: str
    quantity: float
    date: dt.datetime
    txn_id: str
    exchange: str
    cost_basis: float = 0.0

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "quantity": self.quantity,
            "cost_basis": self.cost_basis,
            "date": str(self.date),
            "txn_id": self.txn_id
        }


@dataclass
class Purchase(Transaction):
    qty_disposed: float = 0.0
    full_disposal: bool = False

    def to_dict(self):
        d = super().to_dict()
        d.update({
            "qty_disposed": self.qty_disposed,
            "full_disposal": self.full_disposal
        })
        return d


@dataclass
class Disposal(Transaction):
    price: float = 0.0
    proceeds: float = 0.0
    quantity_reconciled: float = 0.0
    review_required: bool = False
    associated_purchases: List[Purchase] = field(default_factory=list)
    reconciled: bool = False

    def to_dict(self):
        d = super().to_dict()
        d.update({
            "price": self.price,
            "proceeds": self.proceeds,
            "quantity_reconciled": self.quantity_reconciled,
            "review_required": self.review_required,
            "associated_purchases": [p.to_dict() for p in self.associated_purchases],
            "reconciled": self.reconciled
        })
        return d


class ExchangeTaxInfo:
    def __init__(self, exchange: str = "", key_mapping: dict = {}):
        """
        Initializes an instance of ExchangeTaxInfo.

        :param exchange: The name of the exchange.
        :param key_mapping: A dictionary that maps keys in the exchange's transaction format to standardized keys.
        """
        if exchange == "":
            raise ValueError("Broker name must be specified")
        self.exchange = exchange
        self.common_time_format = "%Y-%m-%dT%H:%M:%S.%fZ"
        if key_mapping == {}:
            self.key_mapping = {
                "utc_time": "utc_time",
                "symbol": "symbol",
                "side": "side",
                "price": "price",
                "quantity": "quantity",
                "txn_id": "txn_id",
                "fee": "fee"
            }
        else:
            self.key_mapping = key_mapping
        # List of transactions in the form of a dictionary
        # self.txn_list = []
        self.txns = []
        self.get_txns()
        self.txns = self.raw_txns_to_dataclass(self.txns)
        self.normalize_symbols()

    @abstractmethod
    def get_txns(self):
        """
        Gets the transactions from the exchange.
        """
        pass

    def raw_txn_to_dataclass(self, txn: dict) -> Transaction:
        exchange = self.exchange
        side = txn[self.key_mapping["side"]]
        fee = float(txn[self.key_mapping["fee"]])
        price = float(txn[self.key_mapping["price"]])
        quantity = float(txn[self.key_mapping["quantity"]])
        txid = txn[self.key_mapping["txn_id"]]
        date = txn[self.key_mapping["utc_time"]]
        symbol = txn[self.key_mapping["symbol"]]
        if side == "buy":
            return Purchase(
                symbol=symbol,
                quantity=quantity,
                date=date,
                txn_id=txid,
                exchange=exchange,
                cost_basis=price * quantity + fee
            )
        elif side == "sell":
            return Disposal(
                symbol=symbol,
                quantity=quantity,
                date=date,
                txn_id=txid,
                exchange=exchange,
                price=price,
                proceeds=price * quantity - fee
            )

    def raw_txns_to_dataclass(self, txns: List[dict]) -> List[Transaction]:
        return [self.raw_txn_to_dataclass(txn) for txn in txns]

    def normalize_symbols(self):
        for ix, txn in enumerate(self.txns):
            self.txns[ix].symbol = txn.symbol.replace("-", "")


class CBProTaxInfo(ExchangeTaxInfo):
    def __init__(self, auth_client: cbpro.AuthenticatedClient, tickers: list = ["BTC-USD"]):
        self.auth_client = auth_client
        self.tickers = tickers
        key_mapping = {
            "utc_time": "created_at",
            "symbol": "product_id",
            "side": "side",
            "price": "price",
            "quantity": "size",
            "txn_id": "order_id",
            "fee": "fee"
        }
        super().__init__("Coinbase Pro", key_mapping)

    def get_txns(self):
        for ticker in self.tickers:
            fills = self.auth_client.get_fills(ticker)
            for fill in fills:
                fill["created_at"] = dt.datetime.strptime(
                    fill["created_at"], self.common_time_format)
                self.txns.append(fill)
        return self.txns


class RobinhoodTaxInfo(ExchangeTaxInfo):
    def __init__(self, username: str, password: str, totp: str):
        rh.login(username, password, mfa_code=totp)
        key_mapping = {
            "utc_time": "created_at",
            "symbol": "symbol",
            "side": "side",
            "price": "average_price",
            "quantity": "quantity",
            "txn_id": "id",
            "fee": "fee"
        }
        self.prev_years_1099b = []
        self.symbol_mapping = {}
        super().__init__("Robinhood", key_mapping)

    def get_txns(self):
        orders = rh.get_all_crypto_orders()
        for order in orders:
            if order["state"] == "filled":
                order["fee"] = 0.0
                order["created_at"] = self.conv_to_dt_object(
                    order["created_at"])
                order["symbol"] = self.map_symbol(order["currency_pair_id"])
                self.txns.append(order)
        return self.txns

    def map_symbol(self, id: str) -> str:
        if id not in self.symbol_mapping:
            self.symbol_mapping[id] = rh.get_crypto_quote_from_id(id)["symbol"]
        return self.symbol_mapping[id]

    def conv_to_dt_object(self, datetime_string: str) -> dt.datetime:
        if datetime_string[-1] == "Z":
            return datetime_string
        else:
            strip_timezone_offset = datetime_string[:-6]+"Z"
            datetime_object = dt.datetime.strptime(
                strip_timezone_offset, self.common_time_format)
            timezone_offset = datetime_string[-6:]
            datetime_object += dt.timedelta(
                hours=int(timezone_offset[:3]), minutes=int(timezone_offset[4:]))
            return datetime_object


class StrikeTaxInfo(ExchangeTaxInfo):
    def __init__(self, csv_filename: str):
        self.csv_filename = csv_filename

        key_mapping = {
            "utc_time": "Time (UTC)",
            "symbol": "symbol",
            "side": "side",
            "price": "BTC Price",
            "quantity": "quantity",
            "txn_id": "Transaction ID",
            "fee": "fee"
        }
        super().__init__("Strike", key_mapping)

    def get_txns(self) -> list:
        df = pd.read_csv(self.csv_filename)
        df = df.dropna(how="all")
        temp_txn_list = df.to_dict(orient="records")
        self.txns = []
        for txn in temp_txn_list:
            if txn["Transaction Type"] == "Trade":
                temp_dict = {
                    txn["Currency 1"]: txn["Amount 1"],
                    txn["Currency 2"]: txn["Amount 2"]
                }
                txn["Time (UTC)"] = dt.datetime.strptime(
                    txn["Time (UTC)"], "%b %d %Y %H:%M:%S")
                txn["fee"] = 0.0
                txn["quantity"] = float(temp_dict["BTC"])
                txn["side"] = "buy" if temp_dict["BTC"] > 0 else "sell"
                txn["symbol"] = "BTCUSD"
                self.txns.append(txn)


class Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (Purchase, Disposal)):
            return obj.to_dict()
        elif isinstance(obj, dt.datetime):
            return str(obj)
        return super().default(obj)


class Taxes:
    def __init__(self, Exchanges: List[ExchangeTaxInfo] = [], UndisposedPurchases: List[Purchase] = [], years: List[int] = []):
        self.exchanges = Exchanges
        self.txns = self.init_txns()
        if years:
            self.txns = self.filter_for_years(years)
        self.disposals = [
            txn for txn in self.txns if isinstance(txn, Disposal)]
        self.undisposed_purchases = [
            txn for txn in self.txns if isinstance(txn, Purchase)]
        self.undisposed_purchases.extend(UndisposedPurchases)
        self.disposals = sorted(
            self.disposals, key=operator.attrgetter("date"))
        self.undisposed_purchases = sorted(
            self.undisposed_purchases, key=operator.attrgetter("date"))
        self.disposed_purchases = []

    def init_txns(self):
        txns = []
        for exchange in self.exchanges:
            txns.extend(exchange.txns)
        return sorted(txns, key=operator.attrgetter("date"))

    def filter_for_years(self, years: list):
        txns_tmp = []
        for year in years:
            for txn in self.txns:
                if txn.date.year == year:
                    txns_tmp.append(txn)
        return txns_tmp

    def process_disposal_fifo(self, disposal: Disposal):
        while disposal.quantity_reconciled < disposal.quantity:
            purchase = self.undisposed_purchases.pop(0)
            if purchase.symbol != disposal.symbol:
                self.purchases.append(purchase)
                continue
            elif purchase.date > disposal.date:
                self.undisposed_purchases.append(purchase)
                disposal.review_required = True
                break
            else:
                if purchase.quantity - purchase.qty_disposed >= disposal.quantity - disposal.quantity_reconciled:
                    purchase.qty_disposed += disposal.quantity - disposal.quantity_reconciled
                    disposal.cost_basis += purchase.cost_basis * \
                        (disposal.quantity - disposal.quantity_reconciled) / \
                        disposal.quantity
                    disposal.quantity_reconciled = disposal.quantity
                else:
                    disposal.quantity_reconciled += purchase.quantity - purchase.qty_disposed
                    disposal.cost_basis += purchase.cost_basis * \
                        (purchase.quantity - purchase.qty_disposed) / \
                        disposal.quantity
                    purchase.qty_disposed += purchase.quantity - purchase.qty_disposed
                purchase.full_disposal = (
                    purchase.qty_disposed >= purchase.quantity)
                disposal.reconciled = (
                    disposal.quantity_reconciled >= disposal.quantity)
                disposal.associated_purchases.append(copy(purchase))
                if not purchase.full_disposal:
                    self.undisposed_purchases.insert(0, purchase)
            if purchase.full_disposal:
                self.disposed_purchases.append(purchase)
        self.undisposed_purchases.sort(key=operator.attrgetter("date"))
        return disposal

    def process_disposals_fifo(self) -> List[Disposal]:
        self.undisposed_purchases.sort(key=operator.attrgetter("date"))
        self.disposals.sort(key=operator.attrgetter("date"))
        disposals_tmp = []
        for disposal in self.disposals:
            disposals_tmp.append(self.process_disposal_fifo(disposal))
        self.disposals = disposals_tmp
        return self.disposals

    def to_json(self):
        with open(f"data/disposals_{dt.datetime.now().strftime('%Y-%m-%d')}.json", "w") as f:
            json.dump(self.disposals, f, cls=Encoder)

        with open(f"data/undisposed_purchases_{dt.datetime.now().strftime('%Y-%m-%d')}.json", "w") as f:
            json.dump(self.undisposed_purchases, f, cls=Encoder)

        with open(f"data/disposed_purchases_{dt.datetime.now().strftime('%Y-%m-%d')}.json", "w") as f:
            json.dump(self.disposed_purchases, f, cls=Encoder)

    def to_csv(self):
        disposal_df = pd.DataFrame([disposal.to_dict()
                                   for disposal in self.disposals])
        disposal_df.to_csv(
            f"data/disposals_{dt.datetime.now().strftime('%Y-%m-%d')}.csv")
        undisposed_purchases_df = pd.DataFrame(
            [purchase.to_dict() for purchase in self.undisposed_purchases])
        undisposed_purchases_df.to_csv(
            f"data/undisposed_purchases_{dt.datetime.now().strftime('%Y-%m-%d')}.csv")
        disposed_purchases_df = pd.DataFrame(
            [purchase.to_dict() for purchase in self.disposed_purchases])
        disposed_purchases_df.to_csv(
            f"data/disposed_purchases_{dt.datetime.now().strftime('%Y-%m-%d')}.csv")

    def run(self):
        self.process_disposals_fifo()
        self.to_json()
        self.to_csv()


if __name__ == "__main__":
    load_dotenv()

    CBPRO_PRIVATE_KEY = os.getenv("CBPRO_PRIVATE_KEY")
    CBPRO_PASSPHRASE = os.getenv("CBPRO_PASSPHRASE")
    CBPRO_B64_KEY = os.getenv("CBPRO_B64_KEY")

    RH_USERNAME = os.getenv("RH_USERNAME")
    RH_PASSWORD = os.getenv("RH_PASSWORD")
    RH_TOTP_B32 = os.getenv("RH_TOTP_B32")

    totp = pyotp.TOTP(RH_TOTP_B32).now()

    RH = RobinhoodTaxInfo(RH_USERNAME, RH_PASSWORD, totp)
    STRIKE = StrikeTaxInfo("data/strike_annual_transactions_2022.csv")
    CBPRO = CBProTaxInfo(cbpro.AuthenticatedClient(
        CBPRO_B64_KEY, CBPRO_PRIVATE_KEY, CBPRO_PASSPHRASE))

    Exchanges = [RH, CBPRO, STRIKE]

    TAXES = Taxes(Exchanges, years=[2022])

    TAXES.run()
