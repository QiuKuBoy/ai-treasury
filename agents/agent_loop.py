#!/usr/bin/env python3
"""Emit a steady stream of risk-approved Treasury actions on Monad Testnet."""

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
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

ACTIONS = (
    ("HOLD", Decimal("0.001"), "mETH volatility cooling, maintain allocation"),
    ("REBALANCE", Decimal("0.003"), "mUSDC liquidity improving, rebalance defensively"),
    ("SWAP", Decimal("0.005"), "STM momentum weakening, rotate a small position"),
)


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


def send_transaction(w3, account, contract_call):
    """Build with RPC defaults/estimation and always source nonce from pending."""
    transaction = contract_call.build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "chainId": CHAIN_ID,
        }
    )
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
    parser.add_argument("--min-delay", type=int, default=20)
    parser.add_argument("--max-delay", type=int, default=40)
    args = parser.parse_args()
    if args.rounds < 0:
        parser.error("--rounds must be zero or positive")
    if args.min_delay < 20 or args.max_delay > 40 or args.min_delay > args.max_delay:
        parser.error("delay range must stay within 20-40 seconds")
    return args


def main():
    args = parse_args()
    load_dotenv(ROOT / ".env")
    runner_key = required_secret("RUNNER_PRIVATE_KEY")
    guardian_key = required_secret("GUARDIAN_PRIVATE_KEY")
    secrets = (runner_key, guardian_key)

    deployments = json.loads((ROOT / "docs" / "deployments.json").read_text(encoding="utf-8"))
    treasury_abi = json.loads((ROOT / "docs" / "abis" / "Treasury.json").read_text(encoding="utf-8"))

    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        raise RuntimeError("cannot connect to Monad Testnet RPC")
    if w3.eth.chain_id != CHAIN_ID:
        raise RuntimeError("unexpected chain id: {}".format(w3.eth.chain_id))

    runner = w3.eth.account.from_key(runner_key)
    guardian = w3.eth.account.from_key(guardian_key)
    if runner.address != Web3.to_checksum_address(deployments["agents"]["Runner"]):
        raise RuntimeError("RUNNER_PRIVATE_KEY does not match deployments.json")
    if guardian.address != Web3.to_checksum_address(deployments["agents"]["Guardian"]):
        raise RuntimeError("GUARDIAN_PRIVATE_KEY does not match deployments.json")

    treasury = w3.eth.contract(
        address=Web3.to_checksum_address(deployments["Treasury"]),
        abi=treasury_abi,
    )

    print(
        "agent loop connected chain={} treasury={} runner={} guardian={}".format(
            CHAIN_ID, treasury.address, runner.address, guardian.address
        ),
        flush=True,
    )

    round_index = 0
    while args.rounds == 0 or round_index < args.rounds:
        action_name, amount_mon, reason = ACTIONS[round_index % len(ACTIONS)]
        timestamp = int(time.time())
        proposal_id = Web3.keccak(text="tick-{}".format(timestamp))
        amount_wei = Web3.to_wei(amount_mon, "ether")
        display_round = round_index + 1

        try:
            approve_hash, _ = send_transaction(
                w3,
                guardian,
                treasury.functions.approveProposal(proposal_id),
            )
            print(
                "round={} approve={} proposal={}".format(
                    display_round, approve_hash, proposal_id.hex()
                ),
                flush=True,
            )
        except Exception as error:  # keep the demo loop alive on RPC or tx failures
            print(
                "round={} approve failed: {}".format(
                    display_round, safe_error(error, secrets)
                ),
                file=sys.stderr,
                flush=True,
            )
            round_index += 1
            if args.rounds == 0 or round_index < args.rounds:
                time.sleep(random.randint(args.min_delay, args.max_delay))
            continue

        try:
            execute_hash, receipt = send_transaction(
                w3,
                runner,
                treasury.functions.executeAction(
                    (
                        runner.address,
                        "EXECUTE",
                        action_name,
                        ZERO_ADDRESS,
                        amount_wei,
                        reason,
                        proposal_id,
                    )
                ),
            )
            events = treasury.events.AgentAction().process_receipt(receipt)
            if len(events) != 1:
                raise RuntimeError("expected exactly one AgentAction event")
            event = events[0]["args"]
            if (
                event["agent"] != runner.address
                or event["action"] != action_name
                or event["amount"] != amount_wei
                or event["proposalId"] != proposal_id
            ):
                raise RuntimeError("AgentAction event fields do not match the submitted action")
            print(
                "round={} execute={} AgentAction action={} amountWei={} reason={!r}".format(
                    display_round, execute_hash, action_name, amount_wei, reason
                ),
                flush=True,
            )
        except Exception as error:  # keep the demo loop alive on RPC or tx failures
            print(
                "round={} execute failed: {}".format(
                    display_round, safe_error(error, secrets)
                ),
                file=sys.stderr,
                flush=True,
            )

        round_index += 1
        if args.rounds == 0 or round_index < args.rounds:
            time.sleep(random.randint(args.min_delay, args.max_delay))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("agent loop stopped", flush=True)
    except Exception as fatal_error:
        print("fatal: {}".format(fatal_error), file=sys.stderr, flush=True)
        raise SystemExit(1)
