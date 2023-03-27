# bitcoin_acconting_tool

## Purpose 

---

This tool is used to reconcile Bitcoin disposals for tax purposes.

Most exhanges will send a 1099-B if you have sold cryptocurrency during the past year; however, the 1099 has no knowledge of purchases made on other exchanges. I ran into the accounting issue where I purchased Bitcoin on exchange A, transferred to cold storage, and sold it months later on exchange B. On my 1099 from exchange B, it appeared as pure profit, with a cost basis of zero. This clearly is not ideal and I created this application to keep clear records of my Bitcoin purchases and disposals.

***Most importantly, this application ties specific bitcoin purchases to sales across multiple exchanges***

The program uses a "first in first out" method for accounting. This may not be optimal, and a logical further development would be to consider the tax implications of short vs long term capital gains.

## Execution

---
```bash
$ ./run.sh
```

Builds and runs the application in a docker container, keeping a volume at ./data/ for generated output files.

3 Files Generated:

1. `./data/disposals_yyyy_mm_dd.json`

    *This file contains all immediately pertinent tax information*

   - Note that the first disposal in the list is unreconciled and requires manual review. This is because the program could not find sufficient purchases occuring prior to the sale date to fully reconcile the disposal. 

```json
[
    {
        "symbol": "BTCUSD",
        "exchange": "Robinhood",
        "quantity": 5.161e-05,
        "cost_basis": 0.0,
        "price": 40000.1555562,
        "date": "2022-03-10T12:00:43.127566",
        "txn_id": "1234abcd-1234-1234-1234-123456789abc",
        "fee": 0.0,
        "proceeds": 1.999998748255482,
        "quantity_reconciled": 0.0,
        "review_required": true,
        "associated_purchases": [],
        "reconciled": false,
        "side": "sell"
    },
    {
        "symbol": "BTCUSD",
        "exchange": "Robinhood",
        "quantity": 0.00060269,
        "cost_basis": 15.965485537522802,
        "price": 16592.04,
        "date": "2022-12-20T23:47:51.930305",
        "txn_id": "1234abcd-1234-1234-1234-123456789abc",
        "fee": 0.0,
        "proceeds": 9.9998565876,
        "quantity_reconciled": 0.00060269,
        "review_required": false,
        "associated_purchases": [
            {
                "symbol": "BTCUSD",
                "exchange": "Coinbase Pro",
                "quantity": 0.00032793,
                "cost_basis": 9.4999880337924,
                "price": 28796.78,
                "date": "2022-05-20T22:52:03.162435",
                "txn_id": "1234abcd-1234-1234-1234-123456789abc",
                "fee": 0.0566599683924,
                "qty_disposed": 0.00032793,
                "full_disposal": true,
                "side": "buy"
            },
            {
                "symbol": "BTCUSD",
                "exchange": "Coinbase Pro",
                "quantity": 0.00042496,
                "cost_basis": 9.999919272038401,
                "price": 23391.09,
                "date": "2022-07-10T23:24:32.107785",
                "txn_id": "1234abcd-1234-1234-1234-123456789abc",
                "fee": 0.0596416656384,
                "qty_disposed": 0.00027476000000000003,
                "full_disposal": false,
                "side": "buy"
            }
        ],
        "reconciled": true,
        "side": "sell"
    }
]
```

2. ``./data/undisposed_purchases_yyyy_mm_dd.json``

- This file contains data for all purchases that have not yet been associated with a sale. This information will be useful for the next tax year as it provides a clear snapshot of the current system state, and ensures that only purchases made in the subsequent tax year need to be added.

```json
[
    {
        "symbol": "BTCUSD",
        "exchange": "Coinbase Pro",
        "quantity": 0.01,
        "cost_basis": 203.9775249987512,
        "price": 20000.00,
        "date": "2022-08-10T03:04:41.396405",
        "txn_id": "abcd1234-abcd-1234-1234-123456789abc",
        "fee": 3.9775249987512,
        "qty_disposed": 0.004656190000000001,
        "full_disposal": false,
        "side": "buy"
    }, 
]

```


1. `./data/disposed_purchases_yyyy_mm_dd.json`

- This contains all reconciled purchases.

```json
[
    {
        "symbol": "BTCUSD",
        "exchange": "Coinbase Pro",
        "quantity": 0.00032793,
        "cost_basis": 9.4999880337924,
        "price": 28796.78,
        "date": "2022-05-20T22:52:03.162435",
        "txn_id": "abcd1234-abcd-1234-1234-123456789abc",
        "fee": 0.0566599683924,
        "qty_disposed": 0.00032793,
        "full_disposal": true,
        "side": "buy"
    }, 
]
```


### Configuration for CoinbasePro

---

1. Create a new api key in Coinbase Pro (Adjust the permissions as you desire. We should only need "View")
2. Copy and paste the private key into the .env file `CBPRO_PRIVATE_KEY=SAMPLE`. You will only be shown this key once on Coinbase
3. Fill `CBPRO_B64_KEY=SAMPLE` with the generated Base64 key and `CBPRO_PASSPHRASE=SAMPLE` with the passphrase you chose.

### Configuration for Robinhood

---

1. Follow instructions for programatic multi-factor authentication [here](https://robin-stocks.readthedocs.io/en/latest/quickstart.html#importing-and-logging-in)

***Make sure to set up an authenticator app with the new TOTP Base32 key, otherwise you may lose access to your account!***

2. Record the TOTP Base32 code and fill `RH_TOTP_B32=SAMPLE` in the .env file
3. Enter your information in the .env file:  `RH_USERNAME=SAMPLE` and `RH_PASSWORD=SAMPLE`

### Configuration for Strike

---

1. Maually download your annual transactions as a csv.
2. Edit main.py such that the `StrikeTaxInfo(YOUR_FILENAME_PATH)`


### Configuration for Manually Entered Transactions

---

1. Create a .json file for your transactions in the format of the following sample:

```json
[
    {
        "utc_time": "2022-03-14 12:00:43.127566",
        "symbol": "BTCUSD",
        "side": "buy",
        "price": 20000.00,
        "quantity": 0.0165000,
        "txn_id": "abcd1234-abcd-1234-1234-123456789abc",
        "fee": 0.00
    },
    {
        "utc_time": "2022-03-14 12:01:10.327566",
        "symbol": "BTCUSD",
        "side": "buy",
        "price": 18000.00,
        "quantity": 1.5000000,
        "txn_id": "abcd1234-abcd-1234-1234-123456789abc",
        "fee": 1.50
    },
    {
        "utc_time": "2022-03-14 12:02:15.527566",
        "symbol": "BTCUSD",
        "side": "sell",
        "price": 21000.00,
        "quantity": 0.0080000,
        "txn_id": "abcd1234-abcd-1234-1234-123456789abc",
        "fee": 0.01
    }
]
```