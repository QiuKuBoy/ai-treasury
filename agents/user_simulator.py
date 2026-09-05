#!/usr/bin/env python3
"""Generate realistic multi-user Treasury deposits and withdrawals on Monad Testnet."""

import argparse
import json
import os
import random
import sys
import time
from decimal import Decimal
from pathlib import Path

from web3 import Web3


ROOT = Path(__file__).resolve().parents[1]
RPC_URL = "https://testnet-rpc.monad.xyz"
CHAIN_ID = 10143
USER_ENV_KEYS = (
    ("Scout", "SCOUT_PRIVATE_KEY"),
    ("Ledger", "LEDGER_PRIVATE_KEY"),
    ("Sentinel", "SENTINEL_PRIVATE_KEY"),
)
MIN_DEPOSIT_MILLI_MON = 50
MAX_DEPOSIT_MILLI_MON = 300
WEI_PER_MILLI_MON = 10**15


def load_dotenv(path):
    """Load a minimal KEY=VALUE dotenv file without adding another dependency."""
    if not path.is_file():
        raise RuntimeError("missing .env in project root")

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def required_secret(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("missing required environment variable: {}".format(name))
    return value


def safe_error(error, secrets):
    message = "{}: {}".format(type(error).__name__, error)
    for secret in secrets:
        if secret:
            message = message.replace(secret, "<redacted>")
    return message


def send_transaction(w3, account, contract_call, value=0):
    """Build with RPC gas estimation and always source nonce from pending."""
    transaction_params = {
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        "chainId": CHAIN_ID,
    }
    if value:
        transaction_params["value"] = value

    transaction = contract_call.build_transaction(transaction_params)
    signed = account.sign_transaction(transaction)
    raw_transaction = getattr(signed, "raw_transaction", None)
    if raw_transaction is None:
        raw_transaction = signed.rawTransaction
    tx_hash = w3.eth.send_raw_transaction(raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60, poll_latency=0.5)
    if receipt["status"] != 1:
        raise RuntimeError("transaction reverted: {}".format(tx_hash.hex()))
    return tx_hash.hex(), receipt


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rounds",
        type=int,
        default=0,
        help="number of rounds to run; 0 keeps running until interrupted",
    )
    parser.add_argument("--min-delay", type=int, default=30)
    parser.add_argument("--max-delay", type=int, default=70)
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="optional deterministic random seed for a reproducible smoke run",
    )
    args = parser.parse_args()
    if args.rounds < 0:
        parser.error("--rounds must be zero or positive")
    if args.min_delay < 30 or args.max_delay > 70 or args.min_delay > args.max_delay:
        parser.error("delay range must stay within 30-70 seconds")
    return args


def next_user_index(rng, user_bag, user_count):
    """Choose randomly while ensuring every three-round cycle covers all users."""
    if not user_bag:
        user_bag.extend(range(user_count))
        rng.shuffle(user_bag)
    return user_bag.pop()


def deposit(w3, treasury, account, label, rng):
    shares_before = treasury.functions.sharesOf(account.address).call()
    milli_mon = rng.randint(MIN_DEPOSIT_MILLI_MON, MAX_DEPOSIT_MILLI_MON)
    amount_wei = milli_mon * WEI_PER_MILLI_MON
    tx_hash, receipt = send_transaction(
        w3,
        account,
        treasury.functions.deposit(),
        value=amount_wei,
    )

    events = treasury.events.Deposit().process_receipt(receipt)
    if len(events) != 1:
        raise RuntimeError("expected exactly one Deposit event")
    event = events[0]["args"]
    shares_after = treasury.functions.sharesOf(account.address).call()
    if (
        event["user"] != account.address
        or event["amount"] != amount_wei
        or event["shares"] <= 0
        or shares_after != shares_before + event["shares"]
    ):
        raise RuntimeError("Deposit event fields do not match the confirmed state change")

    amount_mon = Decimal(amount_wei) / Decimal(10**18)
    print(
        "user={} operation=deposit amountMON={} shares={} tx={} Deposit=validated".format(
            label, amount_mon, event["shares"], tx_hash
        ),
        flush=True,
    )
    return tx_hash


def withdraw(w3, treasury, account, label, shares_before):
    withdraw_shares = shares_before // 2
    if withdraw_shares == 0:
        raise RuntimeError("cannot withdraw half of a zero-sized share balance")

    tx_hash, receipt = send_transaction(
        w3,
        account,
        treasury.functions.withdraw(withdraw_shares),
    )
    events = treasury.events.Withdraw().process_receipt(receipt)
    if len(events) != 1:
        raise RuntimeError("expected exactly one Withdraw event")
    event = events[0]["args"]
    shares_after = treasury.functions.sharesOf(account.address).call()
    if (
        event["user"] != account.address
        or event["shares"] != withdraw_shares
        or event["amount"] <= 0
        or shares_after != shares_before - withdraw_shares
    ):
        raise RuntimeError("Withdraw event fields do not match the confirmed state change")

    amount_mon = Decimal(event["amount"]) / Decimal(10**18)
    print(
        "user={} operation=withdraw amountMON={} shares={} tx={} Withdraw=validated".format(
            label, amount_mon, withdraw_shares, tx_hash
        ),
        flush=True,
    )
    return tx_hash


def run(args, secrets):
    deployments = json.loads((ROOT / "docs" / "deployments.json").read_text(encoding="utf-8"))
    treasury_abi = json.loads((ROOT / "docs" / "abis" / "Treasury.json").read_text(encoding="utf-8"))

    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        raise RuntimeError("cannot connect to Monad Testnet RPC")
    if w3.eth.chain_id != CHAIN_ID:
        raise RuntimeError("unexpected chain id: {}".format(w3.eth.chain_id))

    users = []
    for (label, _), private_key in zip(USER_ENV_KEYS, secrets):
        account = w3.eth.account.from_key(private_key)
        expected_address = Web3.to_checksum_address(deployments["agents"][label])
        if account.address != expected_address:
            raise RuntimeError("{}_PRIVATE_KEY does not match deployments.json".format(label.upper()))
        users.append((label, account))

    treasury = w3.eth.contract(
        address=Web3.to_checksum_address(deployments["Treasury"]),
        abi=treasury_abi,
    )
    print(
        "user simulator connected chain={} treasury={} users={}".format(
            CHAIN_ID,
            treasury.address,
            ",".join("{}:{}".format(label, account.address) for label, account in users),
        ),
        flush=True,
    )

    rng = random.Random(args.seed)
    user_bag = []
    round_index = 0
    while args.rounds == 0 or round_index < args.rounds:
        label, account = users[next_user_index(rng, user_bag, len(users))]
        display_round = round_index + 1

        try:
            shares_before = treasury.functions.sharesOf(account.address).call()
            should_deposit = rng.random() < 0.70 or shares_before == 0
            if should_deposit:
                deposit(w3, treasury, account, label, rng)
            else:
                withdraw(w3, treasury, account, label, shares_before)
        except Exception as error:  # keep the demo loop alive on RPC or tx failures
            print(
                "round={} user={} failed: {}".format(
                    display_round, label, safe_error(error, secrets)
                ),
                file=sys.stderr,
                flush=True,
            )

        round_index += 1
        if args.rounds == 0 or round_index < args.rounds:
            delay = rng.randint(args.min_delay, args.max_delay)
            print("next round in {}s".format(delay), flush=True)
            time.sleep(delay)


def main():
    args = parse_args()
    load_dotenv(ROOT / ".env")
    secrets = tuple(required_secret(env_key) for _, env_key in USER_ENV_KEYS)
    try:
        run(args, secrets)
    except KeyboardInterrupt:
        print("user simulator stopped", flush=True)
    except Exception as fatal_error:
        print(
            "fatal: {}".format(safe_error(fatal_error, secrets)),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
