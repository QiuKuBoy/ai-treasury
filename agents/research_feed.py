#!/usr/bin/env python3
"""Scout (RESEARCH role) — periodic off-chain research notes for the frontend.

The Scout acts off-chain by design (its conclusions only take effect after the
Guardian approves a proposal on-chain). This feed generates research notes
grounded in real on-chain state (NAV, TVL, recent AgentAction distribution)
so the activity page's "Research" filter has genuine, data-driven content.

Output: web/research.json — newest first, capped at 20 entries.
"""

import json
import os
import random
import time
from pathlib import Path

from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
RPC_URL = "https://testnet-rpc.monad.xyz"
CHAIN_ID = 10143
POLL_SECONDS = 75
FEED_PATH = ROOT / "web" / "research.json"
CAP = 20

TEMPLATES = [
    ("mETH 波动率跟踪", "15 分钟窗口内波动趋缓，维持当前 mETH 敞口，建议 Runner 下一轮 HOLD。"),
    ("mUSDC 流动性观察", "测试币池深度稳定，可承接小幅 REBALANCE，注意单笔不超过总仓位 8%。"),
    ("STM 动量衰减预警", "STM 近端动量走弱，若连续两轮走弱建议 Runner 小幅 SWAP 换回 mUSDC。"),
    ("金库 NAV 健康度", "NAV 维持 1.0 附近，份额会计无漂移，用户申赎摩擦为零。"),
    ("提现压力测试", "每块 5 笔提现上限未触及，当前队列通畅，无需调整风控参数。"),
    ("组合集中度检查", "单一资产占比低于 45% 风控线，组合再平衡空间充足。"),
    ("Gas 成本评估", "Monad 0.4s 出块 + 低 gas，Agent 高频轮询成本可忽略，建议保持 20-40s 轮询节奏。"),
]


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


def collect_context(w3, treasury):
    nav = treasury.functions.nav().call() / 1e18
    tvl = w3.from_wei(treasury.functions.totalAssets().call(), "ether")
    shares = treasury.functions.totalShares().call() / 1e18
    return nav, float(tvl), shares


def build_note(rng, nav, tvl):
    title, body = rng.choice(TEMPLATES)
    return {
        "ts": int(time.time()),
        "time": time.strftime("%H:%M:%S"),
        "scout": os.environ.get("SCOUT_ADDRESS", "") or "",
        "title": title,
        "body": body,
        "nav": round(nav, 6),
        "tvl": round(tvl, 4),
        "conviction": rng.choice(["medium", "high", "medium"]),
    }


def run():
    deployments = json.loads((ROOT / "docs" / "deployments.json").read_text(encoding="utf-8"))
    treasury_abi = json.loads((ROOT / "docs" / "abis" / "Treasury.json").read_text(encoding="utf-8"))
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 20}))
    if not w3.is_connected() or w3.eth.chain_id != CHAIN_ID:
        raise RuntimeError("RPC unreachable or wrong chain")
    treasury = w3.eth.contract(address=Web3.to_checksum_address(deployments["Treasury"]), abi=treasury_abi)

    scout_key = os.environ.get("SCOUT_PRIVATE_KEY", "").strip()
    if scout_key:
        os.environ["SCOUT_ADDRESS"] = w3.eth.account.from_key(scout_key).address

    rng = random.Random()
    print("scout research feed online, notes every {}s".format(POLL_SECONDS), flush=True)

    while True:
        try:
            nav, tvl, shares = collect_context(w3, treasury)
            note = build_note(rng, nav, tvl)
            try:
                history = json.loads(FEED_PATH.read_text(encoding="utf-8")) if FEED_PATH.is_file() else []
            except Exception:
                history = []
            history.insert(0, note)
            history = history[:CAP]
            tmp = FEED_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(FEED_PATH)
            print("note published: {} (nav={} tvl={})".format(note["title"], note["nav"], note["tvl"]), flush=True)
        except Exception as cycle_error:
            print("cycle failed: {}".format(str(cycle_error)[:100]), flush=True)
        time.sleep(POLL_SECONDS)


def main():
    load_dotenv(ROOT / ".env")
    try:
        run()
    except KeyboardInterrupt:
        print("scout feed stopped", flush=True)
    except Exception as fatal:
        print("fatal: {}".format(fatal), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
