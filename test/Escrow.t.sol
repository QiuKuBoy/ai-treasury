// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AgentRegistry} from "../src/AgentRegistry.sol";
import {Treasury} from "../src/Treasury.sol";
import {Escrow} from "../src/Escrow.sol";
import {TestBase} from "./TestBase.sol";

contract EscrowTest is TestBase {
    AgentRegistry private registry;
    Treasury private treasury;
    Escrow private escrow;

    address private constant LEDGER = address(0x3001);
    address private constant AGENT_ONE = address(0x3002);
    address private constant AGENT_TWO = address(0x3003);

    function setUp() public {
        registry = new AgentRegistry();
        registry.register(LEDGER, AgentRegistry.Role.SETTLE);
        treasury = new Treasury(address(registry));
        escrow = new Escrow(address(registry), address(treasury));
        vm.deal(address(this), 10 ether);
    }

    function testReleaseRequiresDoneTask() public {
        escrow.deposit{value: 1 ether}(1, 1 ether);
        (address[] memory agents, uint256[] memory weights) = _distribution();

        vm.expectRevert(Escrow.InvalidTaskStatus.selector);
        escrow.release(1, agents, weights);
    }

    function testReleaseUsesBasisPointWeights() public {
        escrow.deposit{value: 1 ether}(1, 1 ether);
        vm.prank(LEDGER);
        escrow.markDone(1);
        (address[] memory agents, uint256[] memory weights) = _distribution();

        vm.prank(LEDGER);
        escrow.release(1, agents, weights);

        assertEq(AGENT_ONE.balance, 0.6 ether);
        assertEq(AGENT_TWO.balance, 0.4 ether);
    }

    function testSlashReturnsFundsToTreasury() public {
        escrow.deposit{value: 1 ether}(2, 1 ether);

        vm.prank(LEDGER);
        escrow.slash(2, 0.25 ether);

        assertEq(treasury.totalAssets(), 0.25 ether);
        assertEq(treasury.sharesOf(address(escrow)), 0.25 ether);
    }

    function testInvalidWeightTotalReverts() public {
        escrow.deposit{value: 1 ether}(3, 1 ether);
        escrow.markDone(3);
        (address[] memory agents, uint256[] memory weights) = _distribution();
        weights[1] = 3_999;

        vm.expectRevert(Escrow.InvalidDistribution.selector);
        escrow.release(3, agents, weights);
    }

    function _distribution() private pure returns (address[] memory agents, uint256[] memory weights) {
        agents = new address[](2);
        agents[0] = AGENT_ONE;
        agents[1] = AGENT_TWO;
        weights = new uint256[](2);
        weights[0] = 6_000;
        weights[1] = 4_000;
    }
}
