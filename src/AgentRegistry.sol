// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract AgentRegistry {
    enum Role {
        RESEARCH,
        EXECUTE,
        RISK,
        SETTLE,
        ALERT
    }

    error NotOwner();
    error ZeroAddress();
    error AgentAlreadyRegistered();
    error AgentNotRegistered();
    error RoleAlreadyOccupied();

    address public immutable owner;

    mapping(address => Role) private _roles;
    mapping(address => bool) private _registered;
    mapping(address => bool) private _active;
    mapping(Role => address) public activeAgentByRole;

    event AgentRegistered(address indexed agent, Role role);
    event AgentStatusChanged(address indexed agent, bool active);

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function register(address agent, Role role) external onlyOwner {
        if (agent == address(0)) revert ZeroAddress();
        if (_registered[agent]) revert AgentAlreadyRegistered();
        if (activeAgentByRole[role] != address(0)) revert RoleAlreadyOccupied();

        _registered[agent] = true;
        _roles[agent] = role;
        _active[agent] = true;
        activeAgentByRole[role] = agent;

        emit AgentRegistered(agent, role);
    }

    function setActive(address agent, bool active) external onlyOwner {
        if (!_registered[agent]) revert AgentNotRegistered();

        Role role = _roles[agent];
        if (active) {
            address current = activeAgentByRole[role];
            if (current != address(0) && current != agent) revert RoleAlreadyOccupied();
            activeAgentByRole[role] = agent;
        } else if (activeAgentByRole[role] == agent) {
            activeAgentByRole[role] = address(0);
        }

        _active[agent] = active;
        emit AgentStatusChanged(agent, active);
    }

    function isActive(address agent) external view returns (bool) {
        return _active[agent];
    }

    function roleOf(address agent) external view returns (Role) {
        if (!_registered[agent]) revert AgentNotRegistered();
        return _roles[agent];
    }
}
