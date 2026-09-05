// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IEscrowAgentRegistry {
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

interface ITreasuryDeposit {
    function deposit() external payable;
}

contract Escrow {
    enum TaskStatus {
        NONE,
        FUNDED,
        DONE,
        RELEASED,
        SLASHED
    }

    struct Task {
        uint256 reward;
        TaskStatus status;
    }

    error NotAuthorized();
    error InvalidAddress();
    error InvalidReward();
    error TaskAlreadyExists();
    error InvalidTaskStatus();
    error InvalidDistribution();
    error TransferFailed();
    error Reentrancy();

    uint256 public constant WEIGHT_SCALE = 10_000;

    address public immutable owner;
    address public immutable treasury;
    IEscrowAgentRegistry public immutable agentRegistry;
    mapping(uint256 => Task) public tasks;

    bool private _entered;

    event RewardDeposited(uint256 indexed taskId, uint256 amount);
    event RewardReleased(uint256 indexed taskId, address[] agents, uint256[] amounts);
    event Slashed(uint256 indexed taskId, uint256 amount);

    modifier onlyOwnerOrSettle() {
        if (msg.sender != owner) {
            if (!agentRegistry.isActive(msg.sender)) revert NotAuthorized();
            if (agentRegistry.roleOf(msg.sender) != IEscrowAgentRegistry.Role.SETTLE) {
                revert NotAuthorized();
            }
        }
        _;
    }

    modifier nonReentrant() {
        if (_entered) revert Reentrancy();
        _entered = true;
        _;
        _entered = false;
    }

    constructor(address registry, address treasury_) {
        if (registry == address(0) || treasury_ == address(0)) revert InvalidAddress();
        owner = msg.sender;
        agentRegistry = IEscrowAgentRegistry(registry);
        treasury = treasury_;
    }

    function deposit(uint256 taskId, uint256 reward) external payable {
        if (reward == 0 || msg.value != reward) revert InvalidReward();
        if (tasks[taskId].status != TaskStatus.NONE) revert TaskAlreadyExists();

        tasks[taskId] = Task({reward: reward, status: TaskStatus.FUNDED});
        emit RewardDeposited(taskId, reward);
    }

    function markDone(uint256 taskId) external onlyOwnerOrSettle {
        Task storage task = tasks[taskId];
        if (task.status != TaskStatus.FUNDED) revert InvalidTaskStatus();
        task.status = TaskStatus.DONE;
    }

    function release(uint256 taskId, address[] calldata agents, uint256[] calldata weights)
        external
        onlyOwnerOrSettle
        nonReentrant
    {
        Task storage task = tasks[taskId];
        if (task.status != TaskStatus.DONE) revert InvalidTaskStatus();
        if (agents.length == 0 || agents.length != weights.length) revert InvalidDistribution();

        uint256 weightTotal;
        for (uint256 i; i < weights.length; ++i) {
            if (agents[i] == address(0)) revert InvalidAddress();
            weightTotal += weights[i];
        }
        if (weightTotal != WEIGHT_SCALE) revert InvalidDistribution();

        uint256 reward = task.reward;
        uint256 distributed;
        uint256[] memory amounts = new uint256[](agents.length);
        task.reward = 0;
        task.status = TaskStatus.RELEASED;

        for (uint256 i; i < agents.length; ++i) {
            uint256 amount = i + 1 == agents.length ? reward - distributed : (reward * weights[i]) / WEIGHT_SCALE;
            amounts[i] = amount;
            distributed += amount;

            (bool success,) = payable(agents[i]).call{value: amount}("");
            if (!success) revert TransferFailed();
        }

        emit RewardReleased(taskId, agents, amounts);
    }

    function slash(uint256 taskId, uint256 amount) external onlyOwnerOrSettle nonReentrant {
        Task storage task = tasks[taskId];
        if (task.status != TaskStatus.FUNDED && task.status != TaskStatus.DONE) {
            revert InvalidTaskStatus();
        }
        if (amount == 0 || amount > task.reward) revert InvalidReward();

        task.reward -= amount;
        if (task.reward == 0) task.status = TaskStatus.SLASHED;

        ITreasuryDeposit(treasury).deposit{value: amount}();
        emit Slashed(taskId, amount);
    }
}
