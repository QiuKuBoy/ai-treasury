# AI Treasury — 五智能体制衡的链上金库 / Five-Agent Governed Vault on Monad

> Monad Blitz @ 惠州 · 2026-09-05
> **Live Demo / 在线演示**: http://8.141.125.215:3000
> **Network**: Monad Testnet (Chain ID 10143)

---

## 项目概述 / Overview

**中文**：AI 管钱最大的问题是黑盒与无制衡。AI Treasury 把金库交给五个各司其职的 Agent——Scout（研究）/ Runner（执行）/ Guardian（风控）/ Ledger（结算）/ Sentinel（告警）。Guardian 持有链上**一票否决权**（fail-closed：未获 RISK 角色审批的提案，`executeAction` 一律 revert），所有动作实时上链、可逐笔审计。Escrow 按贡献权重自动分账、失败任务自动罚没，构成可持续的 Agent 经济。依托 Monad 并行 EVM（0.4s 出块 / 0.6s 终局 / 万级 TPS），五 Agent 高频交互零拥堵。

**English**: AI Treasury is an on-chain vault governed by five specialized agents — Scout (research), Runner (execution), Guardian (risk), Ledger (settlement), Sentinel (alerts). Guardian holds on-chain **veto power** (fail-closed: `executeAction` reverts unless the proposal was approved by the RISK role). Every action is emitted as an on-chain event, fully auditable. An Escrow contract distributes rewards by role weights and slashes failed tasks. Built on Monad's parallel EVM (0.4s blocks / 0.6s finality / 10k TPS), the five agents interact at high frequency with zero congestion.

## 主要功能 / Features

- **五权分立 Agent 治理**：每角色同一时刻仅一个 active Agent（AgentRegistry 白名单）
- **fail-closed 风控**：`approveProposal → executeAction` 两段式；未审批执行必 revert；`vetoProposal` 产生 `ActionVetoed` 事件
- **防挤兑提现队列**：每区块最多 5 笔提现
- **ERC4626 风格份额会计**：NAV 1e18 精度，首存 1:1
- **Escrow 激励层**：按 40/20/15/15/10 bps 权重分账，slash 资金回流金库
- **Live 前端**：ethers.js 直连 Monad RPC，TVL / NAV / 持仓 / 事件流全部读真实链上数据；MetaMask 真实存入
- **Agents 常驻循环**：Guardian 审批 + Runner 执行，每 20-40s 产生一笔真实链上动作（PM2 常驻阿里云 VPS）

## 技术栈 / Tech Stack

| 层 | 技术 |
|---|---|
| 合约 | Solidity 0.8.24 · Foundry **1.0.0**（verify 兼容）· 16 项测试全绿（含事件断言与 revert 路径） |
| 链 | Monad Testnet 10143（RPC `testnet-rpc.monad.xyz`） |
| Agents | Python 3.12 · web3.py · nonce pending 管理 · 事件字段校验 · 私钥错误自动脱敏 |
| 前端 | 静态 SPA · ethers.js v6 · 中英双语 i18n · Anthropic × Apple 设计语言 |
| 运维 | 阿里云 ECS Ubuntu 24.04 · PM2 双进程（web :3000 + agents） |

## 合约地址 / Deployments (Monad Testnet)

| 合约 | 地址 |
|---|---|
| Treasury | [`0xE7899C255Cdcb93B1Da6b3B0Ba36853879Cf0654`](https://testnet.monadexplorer.com/address/0xE7899C255Cdcb93B1Da6b3B0Ba36853879Cf0654) |
| AgentRegistry | [`0x3A95786161bbD2bB5824d44B2fD1a2776bd1766e`](https://testnet.monadexplorer.com/address/0x3A95786161bbD2bB5824d44B2fD1a2776bd1766e) |
| Escrow | [`0xB189518c2D622B9cb0ccEcdc8fE1CefeD93eD49c`](https://testnet.monadexplorer.com/address/0xB189518c2D622B9cb0ccEcdc8fE1CefeD93eD49c) |
| mUSDC / mETH / STM | 见 [`docs/deployments.json`](docs/deployments.json) |

## 仓库结构 / Structure

```
src/            四合约：Treasury / AgentRegistry / Escrow / mocks/MockERC20
test/           16 项 Foundry 测试（事件断言 + revert 路径 + 边界双断言）
script/         Deploy.s.sol / Smoke.s.sol（部署 + 链上冒烟）
agents/         agent_loop.py（五 Agent 中的 Guardian+Runner 常驻循环）
web/            index.html（Live 前端，读真实链上数据）
docs/           SPEC.md（三件契约）· deployments.json · abis/
```

## 快速开始 / Quick Start

```bash
forge build && forge test          # 需要 Foundry 1.0.0 + solc 0.8.24
python -m venv venv && venv/bin/pip install -r agents/requirements.txt
venv/bin/python agents/agent_loop.py   # 需 .env（见 .env.example）
# 前端：任意静态服务器托管 web/，如 pm2 serve web 3000 --spa
```

## 安全说明 / Security Notes

- 私钥仅存于 `.env`（已 gitignore），agent 循环内所有异常输出自动脱敏
- 合约层：nonReentrant、checks-effects-interactions、白名单 + 角色双重校验、fail-closed
- 测试网代币无真实价值；主网部署前需完整审计
