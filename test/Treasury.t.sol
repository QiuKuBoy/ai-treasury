// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AgentRegistry} from "../src/AgentRegistry.sol";
import {Treasury} from "../src/Treasury.sol";
import {TestBase} from "./TestBase.sol";

contract TreasuryTest is TestBase {
    AgentRegistry private registry;
    Treasury private treasury;

    address private constant USER = address(0x2001);
    address private constant RUNNER = address(0x2002);
    address private constant GUARDIAN = address(0x2003);
    address private constant OUTSIDER = address(0x2004);
    bytes32 private constant PROPOSAL_ID = keccak256("proposal-1");

    function setUp() public {
        registry = new AgentRegistry();
        registry.register(RUNNER, AgentRegistry.Role.EXECUTE);
        registry.register(GUARDIAN, AgentRegistry.Role.RISK);
        treasury = new Treasury(address(registry));

        vm.deal(USER, 20 ether);
        vm.prank(USER);
        treasury.deposit{value: 10 ether}();
    }

    function testDepositMintsSharesAndNav() public view {
        assertEq(treasury.sharesOf(USER), 10 ether);
        assertEq(treasury.totalAssets(), 10 ether);
        assertEq(treasury.nav(), 1e18);
    }

    function testUnapprovedExecutionReverts() public {
        Treasury.Action memory action = _action();

        vm.prank(RUNNER);
        vm.expectRevert(Treasury.ProposalNotApproved.selector);
        treasury.executeAction(action);
    }

    function testNonWhitelistedExecutionReverts() public {
        Treasury.Action memory action = _action();
        action.agent = OUTSIDER;

        vm.prank(OUTSIDER);
        vm.expectRevert(Treasury.UnauthorizedAgent.selector);
        treasury.executeAction(action);
    }

    function testGuardianApprovalAllowsOneExecution() public {
        vm.prank(GUARDIAN);
        treasury.approveProposal(PROPOSAL_ID);

        Treasury.Action memory action = _action();
        vm.prank(RUNNER);
        treasury.executeAction(action);

        assertTrue(!treasury.approvedProposals(PROPOSAL_ID));
    }

    function testMoreThanFiveWithdrawalsInBlockReverts() public {
        for (uint256 i; i < 5; ++i) {
            vm.prank(USER);
            treasury.withdraw(1 ether);
        }

        vm.prank(USER);
        vm.expectRevert(Treasury.WithdrawalLimitExceeded.selector);
        treasury.withdraw(1 ether);
    }

    function _action() private pure returns (Treasury.Action memory) {
        return Treasury.Action({
            agent: RUNNER,
            role: "EXECUTE",
            action: "HOLD",
            asset: address(0),
            amount: 1 ether,
            reason: "risk approved",
            proposalId: PROPOSAL_ID
        });
    }
}
