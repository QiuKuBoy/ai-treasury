// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {stdJson} from "forge-std/StdJson.sol";

import {Treasury} from "../src/Treasury.sol";
import {Escrow} from "../src/Escrow.sol";

contract Smoke is Script {
    using stdJson for string;

    uint256 private constant MONAD_TESTNET_CHAIN_ID = 10_143;
    bytes32 private constant PROPOSAL_ID = keccak256("smoke-1");

    function run() external {
        require(block.chainid == MONAD_TESTNET_CHAIN_ID, "wrong chain");

        string memory deployments = vm.readFile(string.concat(vm.projectRoot(), "/docs/deployments.json"));
        Treasury treasury = Treasury(payable(deployments.readAddress(".Treasury")));
        Escrow escrow = Escrow(deployments.readAddress(".Escrow"));

        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        uint256 runnerKey = vm.envUint("RUNNER_PRIVATE_KEY");
        uint256 guardianKey = vm.envUint("GUARDIAN_PRIVATE_KEY");
        uint256 ledgerKey = vm.envUint("LEDGER_PRIVATE_KEY");

        address runner = deployments.readAddress(".agents.Runner");
        address guardian = deployments.readAddress(".agents.Guardian");
        address ledger = deployments.readAddress(".agents.Ledger");
        require(vm.addr(runnerKey) == runner, "runner key mismatch");
        require(vm.addr(guardianKey) == guardian, "guardian key mismatch");
        require(vm.addr(ledgerKey) == ledger, "ledger key mismatch");

        vm.startBroadcast(deployerKey);
        treasury.deposit{value: 0.01 ether}();
        vm.stopBroadcast();

        vm.startBroadcast(guardianKey);
        treasury.approveProposal(PROPOSAL_ID);
        vm.stopBroadcast();

        Treasury.Action memory action = Treasury.Action({
            agent: runner,
            role: "EXECUTE",
            action: "HOLD",
            asset: address(0),
            amount: 0.01 ether,
            reason: "smoke test",
            proposalId: PROPOSAL_ID
        });
        vm.startBroadcast(runnerKey);
        treasury.executeAction(action);
        vm.stopBroadcast();

        vm.startBroadcast(deployerKey);
        escrow.deposit{value: 0.001 ether}(1, 0.001 ether);
        vm.stopBroadcast();

        vm.startBroadcast(ledgerKey);
        escrow.markDone(1);
        vm.stopBroadcast();

        address[] memory agents = new address[](5);
        agents[0] = deployments.readAddress(".agents.Scout");
        agents[1] = runner;
        agents[2] = guardian;
        agents[3] = ledger;
        agents[4] = deployments.readAddress(".agents.Sentinel");

        uint256[] memory weights = new uint256[](5);
        weights[0] = 4_000;
        weights[1] = 2_000;
        weights[2] = 1_500;
        weights[3] = 1_500;
        weights[4] = 1_000;

        vm.startBroadcast(ledgerKey);
        escrow.release(1, agents, weights);
        vm.stopBroadcast();
    }
}
