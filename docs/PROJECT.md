# AI Treasury 项目文档

> Monad Blitz @ 惠州 · 2026-09-05
> **Live Demo**：http://8.141.125.215:3000
> **GitHub**：github.com/QiuKuBoy/ai-treasury
> **Network**：Monad Testnet（Chain ID 10143）

---

## 一、项目定位

**AI Treasury** 是一个由**五个角色分工的智能体共同治理的链上金库**。核心命题：

> 让 AI 管钱，但每一笔都经得起审计。

我们回答的问题是：AI 自动理财最大障碍不是模型能力，而是"**怎么让 AI 不拿钱跑路**"。答案是**把信任搬进合约**——用分工 + 制衡代替单一大模型，用 fail-closed 的合约层代替链下约定。

---

## 二、背景与痛点

### 2.1 问题
- **单 Agent 黑盒**：当前主流 AI 理财方案是"一个模型 + 一个私钥"，用户无法验证其决策过程，更无法干预。
- **无制衡**：模型被越狱/误判/作恶时，没有链上机制能阻止资金流出。
- **无经济闭环**：Agent 提供服务的激励机制靠链下记账，不可审计、易被搭便车。

### 2.2 需求
| 需求 | 对应机制 |
|---|---|
| 用户信任 | 决策全链上可查（AgentAction 事件） |
| 权力制衡 | 五角色互锁 + Guardian 一票否决 |
| 经济激励 | Escrow 按角色权重自动分佣 |
| 惩罚作恶 | 失败任务自动 slash 回金库 |
| 高频响应 | Monad 并行 EVM（0.4s 块 / 0.6s 终局） |

---

## 三、核心方案

### 3.1 五角色分工

| 角色 | Role Enum | 职责 | 权限 |
|---|---|---|---|
| **Scout** | RESEARCH | 产出研报/提案 | 无写入 |
| **Runner** | EXECUTE | 执行已批准提案 | `executeAction` |
| **Guardian** | RISK | 风控 + 一票否决 | `approveProposal` / `vetoProposal` |
| **Ledger** | SETTLE | 任务结算 | `escrow.markDone / release / slash` |
| **Sentinel** | ALERT | 告警与盯市 | 无写入 |

每个角色同一时刻**仅一个 active 地址**（AgentRegistry 白名单 + setActive 单例约束），防止角色分裂作恶。

### 3.2 Fail-Closed 工作流

```
Scout 提议 (链下)
    ↓
Guardian approveProposal(bytes32)   ← 必须步骤
    ↓
Runner executeAction(Action)        ← 若未审批直接 revert
    ↓
emit AgentAction(...)               ← 链上可审计
```

或风控反向：

```
Guardian vetoProposal(bytes32, reason)
    ↓
approvedProposals[id] = false
    ↓
emit ActionVetoed(id, guardian, reason)
```

### 3.3 经济激励：Escrow

```
owner/SETTLE  deposit(taskId, reward)   → FUNDED
owner/SETTLE  markDone(taskId)          → DONE
owner/SETTLE  release(taskId, agents[], weights[])
                                       → RELEASED
                                          5 角色按 40/20/15/15/10 bps 分佣
owner/SETTLE  slash(taskId, amount)     → 资金回流 Treasury
                                          emit Slashed
```

**WEIGHT_SCALE = 10_000**，weights 总和必须精确等于，否则 revert `InvalidDistribution`。

---

## 四、技术实现

### 4.1 合约层（Solidity 0.8.24）

| 合约 | 职责 | 关键设计 |
|---|---|---|
| `Treasury.sol` | 金库主合约 | ERC4626 风格份额计价、NAV 1e18 精度、**每块 ≤5 次取款防挤兑**、nonReentrant、checks-effects-interactions |
| `AgentRegistry.sol` | 角色白名单 | 5 Role enum、每角色单 active、isActive + roleOf 双重校验 |
| `Escrow.sol` | 激励层 | onlyOwnerOrSettle 修饰、WEIGHT_SCALE 精确校验、slash 资金回流 |
| `MockERC20.sol` | 测试币 | 18 decimals + mint（部署 mUSDC / mETH / STM 用于 demo） |

**测试覆盖**：16 项 Foundry 测试全绿（事件断言 + revert 路径 + 边界双断言 + 提案生命周期）。

### 4.2 前端层（静态 SPA）

- **ethers.js v6 CDN** 直读 Monad RPC，无后端、无打包
- **真实链上数据**：TVL / NAV / 三持仓 / 份额（`pos-shares` / `pos-value` / `pos-upl`）
- **活动流**：6 类事件过滤（Deposit / Withdraw / AgentAction / ActionVetoed / RewardReleased / Slashed）
- **钱包交互**：MetaMask 连接 / `wallet_requestPermissions` 账户切换器 / `accountsChanged` 自动重渲染 / 真实 `deposit()` 调用
- **设计语言**：Anthropic × Apple 风（暖米白 #FAF9F5 + Claude 橙 #D97757 + 衬线标题 + hairline 分隔 + tabular-nums 等宽数字 + 毛玻璃导航）
- **中英双语**：data-i18n + I18N 字典一键切换

**关键工程细节**：Monad Testnet RPC 的 `eth_getLogs` 仅允许 span ≤ 100 块，前端 `queryFilter` 从 `-9000` 收敛到 `-100` 并 `.catch(() => [])` 兜底。

### 4.3 Agent 循环（Python 3.12 + web3.py）

**agent_loop.py**（Runner + Guardian 双钱包）
- 每 20-40s 轮一轮：HOLD / REBALANCE / SWAP 三策略随机
- 流程：`guardian.approveProposal(proposalId)` → `runner.executeAction(action)`
- 链上事件字段校验（agent / role / action / amount / proposalId）
- nonce 从 pending 获取，防止 pending tx 冲突
- 异常输出自动脱敏（私钥 `<redacted>`）

**user_simulator.py**（多用户模拟）
- 用 Scout / Ledger / Sentinel 三个钱包当"用户"
- 每 30-70s 随机 deposit（0.05-0.3 MON）或 withdraw（一半份额）
- 70% 概率存款 / 30% 概率取款；首次无份额强制存款
- 三用户轮换（Fisher-Yates shuffle 确保 3 轮全覆盖）

### 4.4 部署层（Aliyun ECS Ubuntu 24.04）

- **PM2 三进程**：
  - `web`（`pm2 serve web 3000 --spa`）→ http://8.141.125.215:3000
  - `agents`（agent_loop.py）
  - `user_sim`（user_simulator.py）
- **关键工程细节**：
  - Python 启动用 venv 绝对路径（`pm2 start /opt/.../venv/bin/python -- -u agents/x.py`）
  - 无 ICP 备案，80/443 被阻断，选 :3000 裸 IP 上线
  - 安全组显式放行 3000 端口

---

## 五、现场链上数据（截止 18:52）

| 指标 | 数值 |
|---|---|
| Treasury 总余额 | **8.4942 MON** |
| Total Shares | 8.4942 |
| NAV | **1.000000**（完美 1.0） |
| 链上 AgentAction 事件 | **91+**（HOLD / REBALANCE / SWAP 三策略） |
| 用户 Deposit 事件 | 10+（Scout / Ledger / Sentinel 三用户） |
| 用户 Withdraw 事件 | 2+ |
| ActionVetoed 事件 | 1（Guardian 否决模拟提案） |
| RewardReleased 事件 | 2（Escrow Task 1 + Task 2 完成分佣） |
| Slashed 事件 | 1（Escrow Task 3 部分 slash） |
| 智能体用户分布 | Scout 1.101 / Ledger 0.301 / Sentinel 3.457 shares |

---

## 六、合约地址（Monad Testnet）

| 合约 | 地址 | Explorer |
|---|---|---|
| **Treasury** | `0xE7899C255Cdcb93B1Da6b3B0Ba36853879Cf0654` | [查看](https://testnet.monadexplorer.com/address/0xE7899C255Cdcb93B1Da6b3B0Ba36853879Cf0654) |
| **AgentRegistry** | `0x3A95786161bbD2bB5824d44B2fD1a2776bd1766e` | [查看](https://testnet.monadexplorer.com/address/0x3A95786161bbD2bB5824d44B2fD1a2776bd1766e) |
| **Escrow** | `0xB189518c2D622B9cb0ccEcdc8fE1CefeD93eD49c` | [查看](https://testnet.monadexplorer.com/address/0xB189518c2D622B9cb0ccEcdc8fE1CefeD93eD49c) |
| **mUSDC** | `0x601b49b69b1850EAFe07d0d39075719dd5f0FC70` | [查看](https://testnet.monadexplorer.com/address/0x601b49b69b1850EAFe07d0d39075719dd5f0FC70) |
| **mETH** | `0x94539782c39Aaa0303AF337c78fBBf90FAb24Fd4` | [查看](https://testnet.monadexplorer.com/address/0x94539782c39Aaa0303AF337c78fBBf90FAb24Fd4) |
| **STM** | `0x94efb0edaD57b2C495c09e934d44c7f1DdEa528b` | [查看](https://testnet.monadexplorer.com/address/0x94efb0edaD57b2C495c09e934d44c7f1DdEa528b) |

**Agents（5 角色钱包）**：见 [`docs/deployments.json`](./deployments.json)

---

## 七、使用流程

### 7.1 用户端
1. 打开 http://8.141.125.215:3000
2. MetaMask 切换到 Monad Testnet（Chain ID 10143，RPC `https://testnet-rpc.monad.xyz`）
3. 点击右上角"连接钱包" → 地址显示 → 下拉可**切换账户 / 断开连接**
4. 主页点"存入" → 弹窗输入金额 → MetaMask 签名 → 链上 deposit() 成功
5. 切到**活动流**：6 个过滤按钮任选（全部 / 存款 / 取款 / 代理操作 / 否决 / 奖励 / 惩罚）
6. 切到**智能体**：5 个角色卡显示实时动作计数与最新 reason
7. 切到**仪表盘**：Escrow 结算记录表 + 资产分布

### 7.2 Agent 端（运维）

```bash
# 启动五 agent 中的 Guardian+Runner 常驻循环
cd /opt/ai-treasury
pm2 start /opt/ai-treasury/venv/bin/python --name agents -- -u agents/agent_loop.py

# 启动多用户模拟器（3 个测试用户持续产生存取款）
pm2 start /opt/ai-treasury/venv/bin/python --name user_sim -- -u agents/user_simulator.py

# 查看实时日志
pm2 logs agents
pm2 logs user_sim
```

---

## 八、工程亮点

### 8.1 安全设计
- **Fail-Closed**：合约层强制 approve → execute 两步，未审批必 revert
- **单 active 约束**：每角色同时只允许一个地址活跃
- **防挤兑**：`MAX_WITHDRAWALS_PER_BLOCK = 5`，同块第 6 次取款 revert
- **nonReentrant**：Treasury.withdraw + Escrow.release/slash 全加重入锁
- **CEI 顺序**：checks-effects-interactions，shares 先扣后转账

### 8.2 Monad 原生优势
- **0.4s 块时间**：Guardian approve 后 Runner execute 的链路延迟 < 1s，AI 高频决策不再受区块延迟拖累
- **0.6s 单槽终局**：无重组风险，AI 无需等待确认
- **万级 TPS**：5 agent + 多用户并行操作无拥堵
- **EVM 完全兼容**：Foundry 原生部署，web3.py/ethers.js 直接接入

### 8.3 可审计性
- 所有动作都是**链上事件**：AgentAction / ActionVetoed / Deposit / Withdraw / RewardReleased / Slashed
- 事件字段完整（agent / role / action / amount / reason / proposalId）
- 前端直接 `queryFilter` 拉取，无后端加工，所见即链上真实

### 8.4 经济闭环
- Agent 奖励由 Escrow 按角色权重**自动分配**，无人工干预
- 失败任务自动 slash，资金回流 Treasury 补偿用户
- 未来可扩展：按绩效动态调整权重、引入质押机制

---

## 九、路线图

### 已完成（本次黑客松 6.5h 交付）
- [x] 4 个合约 + 16 项 Foundry 测试全绿
- [x] Deploy 到 Monad Testnet + Blockvision verify
- [x] 前端 SPA（Live 数据 + 钱包切换 + 6 类事件流）
- [x] agent_loop.py（Guardian + Runner 常驻）
- [x] user_simulator.py（3 用户持续产生真实存取款）
- [x] VPS 公网上线 + PM2 三进程守护

### 下一步（1-2 周）
- [ ] **真实 Agent 接入**：Scout 接 LLM（DeepSeek/Claude）产出研报，Runner 接策略引擎真正执行 swap
- [ ] **Envio indexer**：替代前端 queryFilter，支持跨大 block range 的事件查询
- [ ] **多资产**：接真实 ERC20（mUSDC / mETH / STM）的 rebalance 逻辑
- [ ] **告警通道**：Sentinel 接 Telegram / 飞书 webhook

### 主网候选（2-4 周）
- [ ] 完整安全审计（Guardian 私钥 HSM 化）
- [ ] Escrow 权重动态化（按 KPI 调整）
- [ ] 多签治理替代单 owner
- [ ] Monad Mainnet（Chain ID 143）部署

---

## 十、团队与致谢

- **产品设计 + 前端 + 编排**：WorkBuddy
- **合约 + 后端 + 部署**：Codex
- **决策 + 路演 + 测试**：QiuKuBoy

**致谢**：Monad 官方 foundry-monad 模板、Blockvision 浏览器、Aliyun ECS、Foundry 1.0.0。

---

## 附录 A：快速开始（开发者）

```bash
# 克隆
git clone https://github.com/QiuKuBoy/ai-treasury.git && cd ai-treasury

# 合约：测试
forge build && forge test   # 需 Foundry 1.0.0

# 合约：部署（需 .env，参考 .env.example）
forge script script/Deploy.s.sol --broadcast --rpc-url $MONAD_RPC

# Agent：跑常驻循环
python -m venv venv
venv/bin/pip install -r agents/requirements.txt
venv/bin/python agents/agent_loop.py
venv/bin/python agents/user_simulator.py

# 前端：静态托管
cd web && python3 -m http.server 3000
# 或 pm2 serve web 3000 --spa
```

## 附录 B：测试网资源

- RPC：`https://testnet-rpc.monad.xyz`
- Explorer：https://testnet.monadexplorer.com
- Faucet：https://faucet.monad.xyz（每地址 1 次，建议 Deployer 领后转账分发给 Agent）
- Chain ID：10143
- 货币符号：MON

---

**Document version**: v1.0 · 2026-09-05 18:55
**License**: MIT