#!/usr/bin/env python3
"""Sentinel (ALERT role) — read-only on-chain watchdog for the Treasury.

Monitors the last ~100 blocks every cycle (Monad RPC archive limit) and
raises alerts on:
  1. Large aggregate withdrawals in the window   -> WITHDRAWAL_SPIKE
  2. NAV deviation beyond +/- 1%                 -> NAV_DEPEG
  3. New Guardian vetoes                         -> RISK_VETO
  4. New slashing events                         -> SLASH_EVENT

Alerts are printed to stdout (visible via `pm2 logs sentinel`) and appended
to alerts.log. Read-only: the Sentinel key never signs a transaction.
"""

import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
RPC_URL = "https://testnet-rpc.monad.xyz"
CHAIN_ID = 10143
WINDOW_BLOCKS = 100          # Monad RPC eth_getLogs hard limit
POLL_SECONDS = 15
WITHDRAW_SPIKE_MON = Decimal("0.5")
NAV_BAND = (Decimal("0.99"), Decimal("1.01"))
ALERT_LOG = ROOT / "alerts.log"


def load_dotenv(path):
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
        os.environ.setdefault(key.strip(), value.strip())


def raise_alert(tag, detail):
    stamp = time.strftime("%H:%M:%S")
    date_stamp = time.strftime("%Y-%m-%d")
    entry = {"time": stamp, "date": date_stamp, "tag": tag, "detail": detail}
    line = "[{}][{}] {}".format(stamp, tag, detail)
    print("=" * 8 + " ALERT " + "=" * 8, flush=True)
    print(line, flush=True)
    print("=" * 22, flush=True)
    with open(ALERT_LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    sync_web_feed(entry)


def sync_web_feed(entry):
    """Mirror the alert into web/alerts.json so the frontend can poll it."""
    feed_path = ROOT / "web" / "alerts.json"
    try:
        history = json.loads(feed_path.read_text(encoding="utf-8")) if feed_path.is_file() else []
    except Exception:
        history = []
    history.insert(0, entry)
    history = history[:20]
    tmp_path = feed_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(feed_path)


def safe_event_args(log):
    try:
        return log["args"]
    except Exception:
        return {}


def run():
    deployments = json.loads((ROOT / "docs" / "deployments.json").read_text(encoding="utf-8"))
    treasury_abi = json.loads((ROOT / "docs" / "abis" / "Treasury.json").read_text(encoding="utf-8"))
    escrow_abi = json.loads((ROOT / "docs" / "abis" / "Escrow.json").read_text(encoding="utf-8"))

    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        raise RuntimeError("cannot connect to Monad Testnet RPC")
    if w3.eth.chain_id != CHAIN_ID:
        raise RuntimeError("unexpected chain id: {}".format(w3.eth.chain_id))

    sentinel_key = os.environ.get("SENTINEL_PRIVATE_KEY", "").strip()
    if not sentinel_key:
        raise RuntimeError("missing SENTINEL_PRIVATE_KEY")
    sentinel = w3.eth.account.from_key(sentinel_key)

    treasury = w3.eth.contract(address=Web3.to_checksum_address(deployments["Treasury"]), abi=treasury_abi)
    escrow = w3.eth.contract(address=Web3.to_checksum_address(deployments["Escrow"]), abi=escrow_abi)

    print(
        "sentinel watchdog online chain={} treasury={} watcher={} (read-only)".format(
            CHAIN_ID, treasury.address, sentinel.address
        ),
        flush=True,
    )

    last_veto_block = 0
    last_slash_block = 0

    while True:
        latest = w3.eth.block_number
        start = max(0, latest - WINDOW_BLOCKS)

        # Rule 1: withdrawal spike
        try:
            withdraws = treasury.events.Withdraw().get_logs(from_block=start, to_block=latest)
            total = sum(int(log["args"]["amount"]) for log in withdraws)
            total_mon = Decimal(total) / Decimal(10**18)
            if total_mon >= WITHDRAW_SPIKE_MON:
                raise_alert(
                    "WITHDRAWAL_SPIKE",
                    "{} MON withdrawn across {} txs in last {} blocks".format(
                        total_mon, len(withdraws), WINDOW_BLOCKS
                    ),
                )
        except Exception:
            pass

        # Rule 2: NAV depeg
        try:
            nav_raw = treasury.functions.nav().call()
            nav = Decimal(nav_raw) / Decimal(10**18)
            if nav < NAV_BAND[0] or nav > NAV_BAND[1]:
                raise_alert("NAV_DEPEG", "NAV {} outside healthy band {}".format(nav, NAV_BAND))
        except Exception:
            pass

        # Rule 3: new vetoes
        try:
            vetoes = treasury.events.ActionVetoed().get_logs(from_block=start, to_block=latest)
            for log in vetoes:
                if log["blockNumber"] > last_veto_block:
                    args = safe_event_args(log)
                    raise_alert(
                        "RISK_VETO",
                        "Guardian {} vetoed proposal {} reason=\"{}\"".format(
                            args.get("riskAgent", "?")[:10],
                            args.get("proposalId", "?").hex()[:14],
                            args.get("reason", ""),
                        ),
                    )
                    last_veto_block = log["blockNumber"]
        except Exception:
            pass

        # Rule 4: slashing
        try:
            slashes = escrow.events.Slashed().get_logs(from_block=start, to_block=latest)
            for log in slashes:
                if log["blockNumber"] > last_slash_block:
                    args = safe_event_args(log)
                    amount = Decimal(int(args.get("amount", 0))) / Decimal(10**18)
                    raise_alert(
                        "SLASH_EVENT",
                        "task {} slashed {} MON, funds returned to Treasury".format(
                            args.get("taskId", "?"), amount
                        ),
                    )
                    last_slash_block = log["blockNumber"]
        except Exception:
            pass

        time.sleep(POLL_SECONDS)


def main():
    load_dotenv(ROOT / ".env")
    try:
        run()
    except KeyboardInterrupt:
        print("sentinel watchdog stopped", flush=True)
    except Exception as fatal:
        print("fatal: {}".format(fatal), file=sys.stderr, flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
