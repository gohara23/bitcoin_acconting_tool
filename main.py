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
from dataclasses import dataclass
from dataclasses import field
from typing import List


class ExchangeTaxInfo:
    def __init__(self, exchange: str = "", key_mapping: dict = {}):
        if exchange == "":
            raise ValueError("Broker name must be specified")
        self.exchange = exchange
        self.common_time_format = "%Y-%m-%dT%H:%M:%S.%fZ"
        if key_mapping == {}:
            key_mapping = {
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
        self.txn_list = []
        self.txn_std = []

    def get_txns_std_format(self):
        txn_std_format = []
        for txn in self.txn_list:
            txn_std_format.append(self.convert_txn_to_std_format(txn))
        return self.txn_list
    
    def convert_txn_to_std_format(self, txn: dict):
        txn_std_format = {}
        for key in self.key_mapping:
            txn_std_format[key] = txn[self.key_mapping[key]]
        txn_std_format["exchange"] = self.exchange
        txn_std_format["fee"] = float(txn_std_format["fee"])
        txn_std_format["price"] = float(txn_std_format["price"])
        txn_std_format["quantity"] = float(txn_std_format["quantity"])
        if txn_std_format["side"] == "sell":
            txn_std_format["quantity"] = -txn_std_format["quantity"]
        txn_std_format["cost_basis"] = txn_std_format["price"] * txn_std_format["quantity"] + txn_std_format["fee"]
        return txn_std_format
    
    def convert_txns_to_std_format(self):
        self.txn_std = []
        for txn in self.txn_list:
            self.txn_std.append(self.convert_txn_to_std_format(txn))
        return self.txn_std
    
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
                fill["created_at"] = dt.datetime.strptime(fill["created_at"], self.common_time_format)
                self.txn_list.append(fill)
        return self.txn_list
    

class RobinhoodTaxInfo(ExchangeTaxInfo):
    def __init__(self, username: str, password: str, totp: str):
        rh.login(username, password, mfa_code=totp)
        key_mapping = {
            "utc_time": "created_at",
            "symbol": "symbol",
            "side": "side",
            "price": "price",
            "quantity": "quantity",
            "txn_id": "id",
            "fee": "fee"
        }
        self.prev_years_1099b = []
        super().__init__("Robinhood", key_mapping)
        self.symbol_mapping = {}

    def get_txns(self):
        orders = rh.get_all_crypto_orders()
        for order in orders:
            if order["state"] == "filled":
                order["fee"] = 0.0
                order["created_at"] = self.conv_to_dt_object(order["created_at"])
                order["symbol"] = self.map_symbol(order["currency_pair_id"])
                self.txn_list.append(order)
        return self.txn_list
            
    def map_symbol(self, id: str) -> str:
        if id not in self.symbol_mapping:
            self.symbol_mapping[id] = rh.get_crypto_quote_from_id(id)["symbol"]
        return self.symbol_mapping[id]
    
    def conv_to_dt_object(self, datetime_string: str) -> dt.datetime:
        if datetime_string[-1] == "Z":
            return datetime_string
        else:
            strip_timezone_offset = datetime_string[:-6]+"Z"
            datetime_object = dt.datetime.strptime(strip_timezone_offset, self.common_time_format)
            timezone_offset = datetime_string[-6:]
            datetime_object += dt.timedelta(hours=int(timezone_offset[:3]), minutes=int(timezone_offset[4:]))
            return datetime_object

class StrikeTaxInfo(ExchangeTaxInfo):
    def __init__(self, csv_filename:str):
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
        self.txn_list = []
        for txn in temp_txn_list:
            if txn["Transaction Type"] == "Trade":
                temp_dict = {
                    txn["Currency 1"]: txn["Amount 1"],
                    txn["Currency 2"]: txn["Amount 2"]
                }
                txn["Time (UTC)"] = dt.datetime.strptime(txn["Time (UTC)"], "%b %d %Y %H:%M:%S")
                txn["fee"] = 0.0
                txn["quantity"] = float(temp_dict["BTC"])
                txn["side"] = "buy" if temp_dict["BTC"] > 0 else "sell"
                txn["symbol"] = "BTCUSD"
                self.txn_list.append(txn)
        

@dataclass
class Purchase:
    symbol: str
    quantity: float
    cost_basis: float
    date: dt.datetime
    txn_id: str
    qty_disposed: float = 0.0
    full_disposal: bool = False

    def __dict__(self):
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "cost_basis": self.cost_basis,
            "date": str(self.date),
            "txn_id": self.txn_id,
            "qty_disposed": self.qty_disposed,
            "full_disposal": self.full_disposal
        }
    
    def to_dict(self):
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "cost_basis": self.cost_basis,
            "date": str(self.date),
            "txn_id": self.txn_id,
            "qty_disposed": self.qty_disposed,
            "full_disposal": self.full_disposal
        }

@dataclass
class Disposal:
    symbol: str
    quantity: float
    cost_basis: float
    date: dt.datetime
    txn_id: str
    quantity_reconciled: float = 0.0
    review_required: bool = False
    associated_purchases: List[Purchase] = field(default_factory=list)

    def __dict__(self):
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "cost_basis": self.cost_basis,
            "date": str(self.date),
            "txn_id": self.txn_id,
            "quantity_reconciled": self.quantity_reconciled,
            "review_required": self.review_required,
            "associated_purchases": self.associated_purchases
        }
    
    def to_dict(self):
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "cost_basis": self.cost_basis,
            "date": str(self.date),
            "txn_id": self.txn_id,
            "quantity_reconciled": self.quantity_reconciled,
            "review_required": self.review_required,
            "associated_purchases": [p.to_dict() for p in self.associated_purchases]
        }

    
class Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (Purchase, Disposal)):
            return obj.to_dict()
        elif isinstance(obj, dt.datetime):
            return str(obj)
        return super().default(obj)


class TaxInfo:
    def __init__(self, Exchanges: list = []):
        self.exchanges = Exchanges
        self.txn_list = []
        self.disposals = []
        self.purchases = []
        self.disposed_purchases = []
        self.txn_df = pd.DataFrame()

    def get_txns(self):
        for exchange in self.exchanges:
            exchange.get_txns()
            exchange.convert_txns_to_std_format()
            self.txn_list.extend(exchange.txn_std)
        self.normlize_symbols()
        self.sort_txns_by_date()
        return self.txn_list
    
    def normlize_symbols(self):
        for ix, txn in enumerate(self.txn_list):
            txn["symbol"] = txn["symbol"].replace("-", "")
            self.txn_list[ix] = txn

    def sort_txns_by_date(self):
        self.txn_list.sort(key=lambda x: x["utc_time"])

    def get_txns_df(self):
        if self.txn_df.empty:
            self.get_txns()
        self.txn_df = pd.DataFrame(self.txn_list)
        self.txn_df.set_index("utc_time", inplace=True)
        return self.txn_df
    
    def to_csv(self, file_path: str = f"tax_info_{dt.datetime.now().strftime('%Y-%m-%d')}.csv", filter_years: list = []):
        self.get_txns_df()
        if filter_years:
            self.filter_for_years(filter_years)
        self.txn_df.to_csv(f"data/{file_path}")

    def filter_for_years(self, years: list):
        self.txn_df = self.txn_df[self.txn_df.index.year.isin(years)]  

    def init_purchases(self):
        self.purchases = []
        for txn in self.txn_list:
            if txn["side"] == "buy":
                self.purchases.append(Purchase(symbol=txn["symbol"], cost_basis=txn["cost_basis"], quantity=txn["quantity"], date=txn["utc_time"], txn_id=txn["txn_id"]))
        # ensure sorted by date
        self.purchases.sort(key=lambda x: x.date)

    def process_disposals_fifo(self):
        self.init_purchases()
        self.disposals = []
        for txn in self.txn_list:
            if txn["side"] == "sell":
                self.disposals.append(Disposal(symbol=txn["symbol"], cost_basis=abs(txn["cost_basis"]), quantity=abs(txn["quantity"]), date=txn["utc_time"], txn_id=txn["txn_id"]))

        # ensure sorted by date
        self.purchases.sort(key=lambda x: x.date)
        self.disposals.sort(key=lambda x: x.date)
        disposals_temp = []
        for disposal in self.disposals:
            disposals_temp.append(self.process_disposal_fifo(disposal))
            self.purchases.sort(key=lambda x: x.date)
        self.disposals = disposals_temp

    def process_disposal_fifo(self, disposal: Disposal):
        while disposal.quantity_reconciled < disposal.quantity:
            purchase = self.purchases.pop(0)
            if purchase.symbol != disposal.symbol:
                self.purchases.append(purchase)
            elif purchase.date > disposal.date:
                # reconcilation requires previous tax year
                self.purchases.append(purchase)
                disposal.review_required = True
                break
            elif purchase.quantity - purchase.qty_disposed >= disposal.quantity - disposal.quantity_reconciled:
                purchase.qty_disposed += disposal.quantity - disposal.quantity_reconciled
                disposal.quantity_reconciled = disposal.quantity
                disposal.cost_basis += purchase.cost_basis * purchase.quantity / disposal.quantity
                disposal.associated_purchases.append(purchase)
                self.purchases.insert(0, purchase)
            else:
                disposal.quantity_reconciled += purchase.quantity
                purchase.qty_disposed += purchase.quantity - purchase.qty_disposed
                purchase.full_disposal = True
                self.disposed_purchases.append(purchase)
                disposal.cost_basis += purchase.cost_basis * purchase.quantity / disposal.quantity
                disposal.associated_purchases.append(purchase)
        return disposal
    
    def filter_to_years(self, years: list):
        self.disposals = [disposal for disposal in self.disposals if disposal.date.year in years]
        self.purchases = [purchase for purchase in self.purchases if purchase.date.year in years]
        self.txn_list = [txn for txn in self.txn_list if txn["utc_time"].year in years]

    def disposals_and_purchases_to_json(self):
        with open(f"data/disposals_{dt.datetime.now().strftime('%Y-%m-%d')}.json", "w") as f:
            json.dump(self.disposals, f, cls=Encoder)

        with open(f"data/open_purchases_{dt.datetime.now().strftime('%Y-%m-%d')}.json", "w") as f:
            json.dump(self.purchases, f, cls=Encoder)

        with open(f"data/disposed_purchases_{dt.datetime.now().strftime('%Y-%m-%d')}.json", "w") as f:
            json.dump(self.disposed_purchases, f, cls=Encoder)
        
    def run(self, filter_years: list = []):
        self.get_txns()
        self.filter_to_years(filter_years)
        self.process_disposals_fifo()
        self.to_csv()
        self.disposals_and_purchases_to_json()



       

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
    CBPRO = CBProTaxInfo(cbpro.AuthenticatedClient(CBPRO_B64_KEY, CBPRO_PRIVATE_KEY, CBPRO_PASSPHRASE))
    STRIKE = StrikeTaxInfo("data/strike_annual_transactions_2022.csv")


    RH1099_FILENAMES = [
        "data/robinhood_crypto_1099_2020.csv",
        "data/robinhood_crypto_1099_2021.csv",
    ]

    Exchanges = [RH, CBPRO, STRIKE]

    TAX_INFO = TaxInfo(Exchanges)
    TAX_INFO.run(filter_years=[2022])
    # TAX_INFO.to_csv(filter_years=[2022]) 
    # TAX_INFO.filter_to_years([2022])
    # TAX_INFO.process_disposals_fifo()





