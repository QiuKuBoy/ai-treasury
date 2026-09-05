#!/usr/bin/env python3
"""Server-side history indexer for the AI Treasury frontend.

Monad Testnet RPC only allows ~100-block eth_getLogs spans and no historical
eth_getCode, so the browser cannot fetch full event history and the deploy
block cannot be binary-searched. This indexer estimates the deployment block
from wall-clock time, pulls raw logs for both contracts in 95-block chunks
(one call per chunk covering both addresses), decodes locally by topic0, and
writes web/history.json incrementally.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
RPC_URL = "https://testnet-rpc.monad.xyz"
CHAIN_ID = 10143
SPAN = 95
POLL_SECONDS = 30
MAX_CHUNKS_PER_CYCLE = 40
BACKFILL_BLOCKS = 24000  # ~2.7h at 0.4s blocks, covers today's sprint window
HISTORY_PATH = ROOT / "web" / "history.json"


def load_dotenv(path):
    if not path.is_file():
        raise RuntimeError("missing .env in project root")
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        os.environ.setdefault(key.strip(), value.strip())


def to_plain(value):
    if isinstance(value, (list, tuple)):
        return [to_plain(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return str(value)


def topic_hex(value):
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    text = str(value)
    return text if text.startswith("0x") else "0x" + text


def build_decoders(treasury, escrow):
    decoders = {}
    for contract, mapping in (
        (treasury, (("AgentAction", "acts"), ("ActionVetoed", "vetoes"), ("Deposit", "deps"), ("Withdraw", "wds"))),
        (escrow, (("RewardReleased", "rels"), ("Slashed", "sla"))),
    ):
        for name, key in mapping:
            event = getattr(contract.events, name)
            decoders[topic_hex(event.topic).lower()] = (event, key, contract.address)
    return decoders


def fetch_range(w3, contracts, start, end, latest_ts, latest_bn):
    rows = {"acts": [], "vetoes": [], "deps": [], "wds": [], "rels": [], "sla": []}
    for contract, event_map in contracts:
        for event_name, key in event_map:
            event = getattr(contract.events, event_name)()
            try:
                logs = event.get_logs(from_block=start, to_block=end)
            except Exception:
                continue
            for log in logs:
                try:
                    raw_args = log["args"]
                    arg_values = list(raw_args.values()) if hasattr(raw_args, "values") else list(raw_args)
                    args = to_plain(arg_values)
                except Exception:
                    continue
                try:
                    ts = int(latest_ts - (latest_bn - log["blockNumber"]) * 2.5)
                    txh = log["transactionHash"]
                    tx_str = Web3.to_hex(txh) if isinstance(txh, (bytes, bytearray)) else str(txh)
                    rows[key].append({
                        "args": args,
                        "blockNumber": int(log["blockNumber"]),
                        "transactionHash": tx_str,
                        "index": int(log["logIndex"]),
                        "ts": max(0, ts),
                    })
                except Exception as row_error:
                    print("row decode failed: {} | log repr: {}".format(row_error, repr(log)[:200]), flush=True)
    return rows


def merge_rows(base, incoming):
    seen = set()
    for rows in base.values():
        for r in rows:
            if isinstance(r, dict):
                seen.add((r["transactionHash"], r["index"]))
    for key, rows in incoming.items():
        bucket = base.setdefault(key, [])
        for row in rows:
            marker = (row["transactionHash"], row["index"])
            if marker not in seen:
                seen.add(marker)
                bucket.append(row)
    for key in base:
        base[key].sort(key=lambda r: (r["blockNumber"], r["index"]), reverse=True)
    return base


def save_history(state, last_block):
    payload = {
        "lastBlock": last_block,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": state,
    }
    tmp = HISTORY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(HISTORY_PATH)


def run():
    deployments = json.loads((ROOT / "docs" / "deployments.json").read_text(encoding="utf-8"))
    treasury_abi = json.loads((ROOT / "docs" / "abis" / "Treasury.json").read_text(encoding="utf-8"))
    escrow_abi = json.loads((ROOT / "docs" / "abis" / "Escrow.json").read_text(encoding="utf-8"))

    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
    if not w3.is_connected() or w3.eth.chain_id != CHAIN_ID:
        raise RuntimeError("RPC unreachable or wrong chain")

    treasury = w3.eth.contract(address=Web3.to_checksum_address(deployments["Treasury"]), abi=treasury_abi)
    escrow = w3.eth.contract(address=Web3.to_checksum_address(deployments["Escrow"]), abi=escrow_abi)
    contracts = (
        (treasury, (("AgentAction", "acts"), ("ActionVetoed", "vetoes"), ("Deposit", "deps"), ("Withdraw", "wds"))),
        (escrow, (("RewardReleased", "rels"), ("Slashed", "sla"))),
    )

    if HISTORY_PATH.is_file():
        try:
            saved = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            state, last_block = saved.get("events", {}), saved.get("lastBlock", 0)
        except Exception:
            state, last_block = {}, 0
    else:
        state, last_block = {}, 0

    while True:
        latest = w3.eth.block_number
        latest_ts = w3.eth.get_block(latest)["timestamp"]
        start = last_block if last_block else max(1, latest - BACKFILL_BLOCKS)
        start = max(1, min(start, latest - SPAN))
        chunks = 0
        cursor = start
        try:
            while cursor <= latest and chunks < MAX_CHUNKS_PER_CYCLE:
                end = min(cursor + SPAN - 1, latest)
                incoming = fetch_range(w3, contracts, cursor, end, latest_ts, latest)
                state = merge_rows(state, incoming)
                cursor = end + 1
                chunks += 1
                time.sleep(0.12)
            if chunks:
                last_block = latest
                save_history(state, last_block)
                counts = {k: len(v) for k, v in state.items()}
                print("indexer: synced to block {} (+{} chunks) total={}".format(latest, chunks, counts), flush=True)
        except Exception as cycle_error:
            import traceback
            traceback.print_exc()
            last_block = max(1, cursor - SPAN)
            save_history(state, last_block)
            print("cycle failed near block {}: {}".format(cursor, str(cycle_error)[:100]), flush=True)
        time.sleep(POLL_SECONDS)


def main():
    load_dotenv(ROOT / ".env")
    try:
        run()
    except KeyboardInterrupt:
        print("indexer stopped", flush=True)
    except Exception as fatal:
        print("fatal: {}".format(fatal), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
