# AI Treasury 三件契约（Contracts Spec v1.0）

> **本文件是 Codex 实现的唯一依据**。接口签名、事件名、字段名不可自行改动；有歧义必须先问人。
> 每次契约变更：WorkBuddy 更新本文件 → 复制到 `ai-treasury/docs/SPEC.md` → git commit（形成版本历史）。

---

## 契约 1：Solidity 合约接口

### 1.1 `Treasury.sol` — 核心金库

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface ITreasury {
    // ---- 用户面 ----
    function deposit() external payable;
    function withdraw(uint256 shares) external;
    function totalAssets() external view returns (uint256);
    function nav() external view returns (uint256);            // 1e18 精度
    function sharesOf(address user) external view returns (uint256);

    // ---- Agent 面 ----
    struct Action {
        address agent;
        string  role;        // "RESEARCH"|"EXECUTE"|"RISK"|"SETTLE"|"ALERT"
        string  action;      // "SWAP"|"REBALANCE"|"HOLD"
        address asset;       // token 地址，address(0) = MON
        uint256 amount;
        string  reason;
        bytes32 proposalId;
    }

    /// 仅 AgentRegistry 白名单内的 EXECUTE 角色可调用
    function executeAction(Action calldata action) external;

    /// Guardian (RISK) 审批提案；未审批的 proposalId 执行必须 revert（fail-closed）
    function approveProposal(bytes32 proposalId) external;

    // ---- 事件（Envio 按事件名订阅，名字不可改）----
    event Deposit(address indexed user, uint256 amount, uint256 shares);
    event Withdraw(address indexed user, uint256 shares, uint256 amount);
    event AgentAction(
        address indexed agent, string role, string action,
        address asset, uint256 amount, string reason, bytes32 indexed proposalId
    );
    event ActionVetoed(bytes32 indexed proposalId, address indexed riskAgent, string reason);
}
```

**安全约束（实现时必须满足）**：
1. `executeAction`：`require(AgentRegistry.isActive(msg.sender))`，且角色必须为 EXECUTE
2. `executeAction`：`require(approvedProposals[proposalId])` —— Guardian 未审批 → revert（fail-closed）
3. `approveProposal`：仅 RISK 角色可调用
4. 提现队列：每块最多处理 5 笔 withdraw（`withdrawalsInBlock[block.number] <= 5`）
5. 份额会计：首笔存款 1:1（amount == shares），之后 `shares = amount * totalShares / totalAssets`
6. 合约不持私钥、不做外部调用（除 ERC20 transfer）

### 1.2 `AgentRegistry.sol` — Agent 白名单

```solidity
enum Role { RESEARCH, EXECUTE, RISK, SETTLE, ALERT }

function register(address agent, Role role) external onlyOwner;
function setActive(address agent, bool active) external onlyOwner;
function isActive(address agent) external view returns (bool);
function roleOf(address agent) external view returns (Role);

event AgentRegistered(address indexed agent, Role role);
event AgentStatusChanged(address indexed agent, bool active);
```

**约束**：每个 Role 同时只能有一个 active agent（比赛简化）；owner = 队长多签/EOA。

### 1.3 `Escrow.sol` — 结算层

```solidity
function deposit(uint256 taskId, uint256 reward) external payable;
function release(uint256 taskId, address[] calldata agents, uint256[] calldata weights) external;
function slash(uint256 taskId, uint256 amount) external;   // 仅 SETTLE 角色或 owner

event RewardDeposited(uint256 indexed taskId, uint256 amount);
event RewardReleased(uint256 indexed taskId, address[] agents, uint256[] amounts);
event Slashed(uint256 indexed taskId, uint256 amount);
```

**约束**：release 前 require task 状态为 DONE；权重总和校验；slash 资金回流 Treasury。

### 1.4 `MockERC20.sol` — 测试资产

标准 ERC20 + `function mint(address to, uint256 amt) external`（public，测试网专用）。
部署 3 个实例：`mUSDC`、`mETH`、`STM`（18 decimals），初始 mint 给 Treasury。

---

## 契约 2：Envio 索引 Schema

```graphql
type Deposit @entity {
  id: Bytes!
  user: Bytes!
  amount: BigInt!
  shares: BigInt!
  ts: BigInt!
}

type AgentAction @entity {
  id: Bytes!
  agent: Bytes!
  role: String!
  action: String!
  asset: Bytes!
  amount: BigInt!
  reason: String!
  proposalId: Bytes!
  txHash: Bytes!
  ts: BigInt!
}

type VetoEvent @entity {
  id: Bytes!
  riskAgent: Bytes!
  proposalId: Bytes!
  reason: String!
  txHash: Bytes!
  ts: BigInt!
}

type EscrowRelease @entity {
  id: Bytes!
  taskId: BigInt!
  total: BigInt!
  agents: [Bytes!]!
  amounts: [BigInt!]!
  txHash: Bytes!
  ts: BigInt!
}
```

订阅事件名（与合约 1.1 严格一致）：`Deposit` / `Withdraw` / `AgentAction` / `ActionVetoed` / `RewardReleased` / `Slashed`。

---

## 契约 3：Agent 提案 JSON Schema（VPS 编排层）

```json
{
  "type": "object",
  "required": ["agent", "role", "action", "reason", "confidence", "ts"],
  "properties": {
    "agent":       { "type": "string", "enum": ["Scout", "Runner", "Guardian", "Ledger", "Sentinel"] },
    "role":        { "type": "string", "enum": ["RESEARCH", "EXECUTE", "RISK", "SETTLE", "ALERT"] },
    "action":      { "type": "string", "enum": ["PROPOSE_REALLOCATE", "SWAP", "APPROVE", "VETO", "SETTLE", "ALERT"] },
    "asset":       { "type": "string", "pattern": "^0x[a-fA-F0-9]{40}$" },
    "amount":      { "type": "string", "description": "wei 字符串" },
    "reason":      { "type": "string", "maxLength": 200 },
    "confidence":  { "type": "number", "minimum": 0, "maximum": 1 },
    "proposalId":  { "type": "string", "pattern": "^0x[a-fA-F0-9]{64}$" },
    "ts":          { "type": "integer" }
  }
}
```

**Agent 行为约束**：
- Scout（RESEARCH）只产出提案，不写链
- Guardian（RISK）消费提案 → 输出 APPROVE 或 VETO；LLM 超时 = VETO（fail-closed）
- Runner（EXECUTE）只执行已 APPROVE 的提案
- Ledger（SETTLE）日终对账 → 调用 Escrow.release
- Sentinel（ALERT）监听异常 → webhook 推送，不写链

---

## 附录：网络与部署常量

| 项 | 值 |
|---|---|
| Testnet RPC | `https://testnet-rpc.monad.xyz` |
| Testnet Chain ID | `10143` (0x279F) |
| 水龙头 | `https://faucet.monad.xyz` |
| 浏览器 | `https://testnet.monadexplorer.com/` |
| Mainnet RPC（bonus） | `https://rpc.monad.xyz`，Chain `143` |
| Foundry 版本 | **必须 1.0.0**（1.1.0 无法 verify） |
| 脚手架 | `github.com/monad-developers/foundry-monad` |
| Agent 钱包预算 | 每个 0.5 test MON（gas 足够） |
