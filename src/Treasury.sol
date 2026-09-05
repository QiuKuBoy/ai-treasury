// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IAgentRegistry {
    enum Role {
        RESEARCH,
        EXECUTE,
        RISK,
        SETTLE,
        ALERT
    }

    function isActive(address agent) external view returns (bool);
    function roleOf(address agent) external view returns (Role);
}

contract Treasury {
    struct Action {
        address agent;
        string role;
        string action;
        address asset;
        uint256 amount;
        string reason;
        bytes32 proposalId;
    }

    error ZeroDeposit();
    error ZeroShares();
    error InsufficientShares();
    error WithdrawalLimitExceeded();
    error NativeTransferFailed();
    error UnauthorizedAgent();
    error InvalidAgent();
    error InvalidRole();
    error InvalidProposal();
    error ProposalNotApproved();
    error Reentrancy();

    uint256 private constant NAV_SCALE = 1e18;
    uint256 private constant MAX_WITHDRAWALS_PER_BLOCK = 5;
    bytes32 private constant EXECUTE_ROLE_HASH = keccak256("EXECUTE");

    IAgentRegistry public immutable agentRegistry;
    uint256 public totalShares;
    mapping(address => uint256) private _shares;
    mapping(bytes32 => bool) public approvedProposals;
    mapping(uint256 => uint256) public withdrawalsInBlock;

    bool private _entered;

    event Deposit(address indexed user, uint256 amount, uint256 shares);
    event Withdraw(address indexed user, uint256 shares, uint256 amount);
    event AgentAction(
        address indexed agent,
        string role,
        string action,
        address asset,
        uint256 amount,
        string reason,
        bytes32 indexed proposalId
    );
    event ActionVetoed(bytes32 indexed proposalId, address indexed riskAgent, string reason);

    modifier nonReentrant() {
        if (_entered) revert Reentrancy();
        _entered = true;
        _;
        _entered = false;
    }

    constructor(address registry) {
        if (registry == address(0)) revert InvalidAgent();
        agentRegistry = IAgentRegistry(registry);
    }

    function deposit() external payable {
        if (msg.value == 0) revert ZeroDeposit();

        uint256 assetsBefore = address(this).balance - msg.value;
        uint256 shares = totalShares == 0 || assetsBefore == 0 ? msg.value : (msg.value * totalShares) / assetsBefore;
        if (shares == 0) revert ZeroShares();

        totalShares += shares;
        _shares[msg.sender] += shares;

        emit Deposit(msg.sender, msg.value, shares);
    }

    function withdraw(uint256 shares) external nonReentrant {
        if (shares == 0) revert ZeroShares();
        if (_shares[msg.sender] < shares) revert InsufficientShares();
        if (withdrawalsInBlock[block.number] >= MAX_WITHDRAWALS_PER_BLOCK) {
            revert WithdrawalLimitExceeded();
        }

        uint256 amount = (shares * address(this).balance) / totalShares;
        withdrawalsInBlock[block.number] += 1;
        _shares[msg.sender] -= shares;
        totalShares -= shares;

        (bool success,) = payable(msg.sender).call{value: amount}("");
        if (!success) revert NativeTransferFailed();

        emit Withdraw(msg.sender, shares, amount);
    }

    function totalAssets() external view returns (uint256) {
        return address(this).balance;
    }

    function nav() external view returns (uint256) {
        if (totalShares == 0) return NAV_SCALE;
        return (address(this).balance * NAV_SCALE) / totalShares;
    }

    function sharesOf(address user) external view returns (uint256) {
        return _shares[user];
    }

    function executeAction(Action calldata action) external {
        _requireActiveRole(msg.sender, IAgentRegistry.Role.EXECUTE);
        if (action.agent != msg.sender) revert InvalidAgent();
        if (keccak256(bytes(action.role)) != EXECUTE_ROLE_HASH) revert InvalidRole();
        if (!approvedProposals[action.proposalId]) revert ProposalNotApproved();

        approvedProposals[action.proposalId] = false;
        emit AgentAction(
            action.agent, action.role, action.action, action.asset, action.amount, action.reason, action.proposalId
        );
    }

    function approveProposal(bytes32 proposalId) external {
        _requireActiveRole(msg.sender, IAgentRegistry.Role.RISK);
        if (proposalId == bytes32(0)) revert InvalidProposal();
        approvedProposals[proposalId] = true;
    }

    function vetoProposal(bytes32 proposalId, string calldata reason) external {
        _requireActiveRole(msg.sender, IAgentRegistry.Role.RISK);
        if (proposalId == bytes32(0)) revert InvalidProposal();
        approvedProposals[proposalId] = false;
        emit ActionVetoed(proposalId, msg.sender, reason);
    }

    function _requireActiveRole(address agent, IAgentRegistry.Role role) private view {
        if (!agentRegistry.isActive(agent)) revert UnauthorizedAgent();
        if (agentRegistry.roleOf(agent) != role) revert UnauthorizedAgent();
    }
}
