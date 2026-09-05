// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AgentRegistry} from "../src/AgentRegistry.sol";
import {TestBase} from "./TestBase.sol";

contract AgentRegistryTest is TestBase {
    AgentRegistry private registry;
    address private constant RUNNER = address(0x1001);
    address private constant OTHER = address(0x1002);

    function setUp() public {
        registry = new AgentRegistry();
    }

    function testRegisterCreatesActiveAgent() public {
        registry.register(RUNNER, AgentRegistry.Role.EXECUTE);

        assertTrue(registry.isActive(RUNNER));
        assertEq(uint256(registry.roleOf(RUNNER)), uint256(AgentRegistry.Role.EXECUTE));
        assertEq(registry.activeAgentByRole(AgentRegistry.Role.EXECUTE), RUNNER);
    }

    function testOnlyOneActiveAgentPerRole() public {
        registry.register(RUNNER, AgentRegistry.Role.EXECUTE);

        vm.expectRevert(AgentRegistry.RoleAlreadyOccupied.selector);
        registry.register(OTHER, AgentRegistry.Role.EXECUTE);

        registry.setActive(RUNNER, false);
        registry.register(OTHER, AgentRegistry.Role.EXECUTE);
        assertTrue(registry.isActive(OTHER));
    }

    function testNonOwnerCannotRegister() public {
        vm.prank(OTHER);
        vm.expectRevert(AgentRegistry.NotOwner.selector);
        registry.register(RUNNER, AgentRegistry.Role.EXECUTE);
    }
}
