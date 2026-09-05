// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";

import {AgentRegistry} from "../src/AgentRegistry.sol";
import {Treasury} from "../src/Treasury.sol";
import {Escrow} from "../src/Escrow.sol";
import {MockERC20} from "../src/mocks/MockERC20.sol";

contract Deploy is Script {
    uint256 private constant MONAD_TESTNET_CHAIN_ID = 10_143;
    uint256 private constant INITIAL_TOKEN_BALANCE = 10_000 ether;

    struct Agents {
        address scout;
        address runner;
        address guardian;
        address ledger;
        address sentinel;
    }

    struct Contracts {
        AgentRegistry registry;
        Treasury treasury;
        Escrow escrow;
        MockERC20 musdc;
        MockERC20 meth;
        MockERC20 stm;
    }

    function run() external {
        require(block.chainid == MONAD_TESTNET_CHAIN_ID, "wrong chain");

        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        Agents memory agents = Agents({
            scout: vm.addr(vm.envUint("SCOUT_PRIVATE_KEY")),
            runner: vm.addr(vm.envUint("RUNNER_PRIVATE_KEY")),
            guardian: vm.addr(vm.envUint("GUARDIAN_PRIVATE_KEY")),
            ledger: vm.addr(vm.envUint("LEDGER_PRIVATE_KEY")),
            sentinel: vm.addr(vm.envUint("SENTINEL_PRIVATE_KEY"))
        });
        Contracts memory deployed;

        vm.startBroadcast(deployerKey);

        deployed.registry = new AgentRegistry();
        deployed.treasury = new Treasury(address(deployed.registry));
        deployed.escrow = new Escrow(address(deployed.registry), address(deployed.treasury));

        deployed.musdc = new MockERC20("Mock USDC", "mUSDC");
        deployed.meth = new MockERC20("Mock ETH", "mETH");
        deployed.stm = new MockERC20("Monad Test Meme", "STM");

        deployed.registry.register(agents.scout, AgentRegistry.Role.RESEARCH);
        deployed.registry.register(agents.runner, AgentRegistry.Role.EXECUTE);
        deployed.registry.register(agents.guardian, AgentRegistry.Role.RISK);
        deployed.registry.register(agents.ledger, AgentRegistry.Role.SETTLE);
        deployed.registry.register(agents.sentinel, AgentRegistry.Role.ALERT);

        deployed.musdc.mint(address(deployed.treasury), INITIAL_TOKEN_BALANCE);
        deployed.meth.mint(address(deployed.treasury), INITIAL_TOKEN_BALANCE);
        deployed.stm.mint(address(deployed.treasury), INITIAL_TOKEN_BALANCE);

        vm.stopBroadcast();

        _writeDeployments(deployed, agents);

        console2.log("AgentRegistry", address(deployed.registry));
        console2.log("Treasury", address(deployed.treasury));
        console2.log("Escrow", address(deployed.escrow));
        console2.log("mUSDC", address(deployed.musdc));
        console2.log("mETH", address(deployed.meth));
        console2.log("STM", address(deployed.stm));
    }

    function _writeDeployments(Contracts memory deployed, Agents memory agents) private {
        string memory json = string(
            abi.encodePacked(
                '{"chainId":10143,"Treasury":"',
                vm.toString(address(deployed.treasury)),
                '","AgentRegistry":"',
                vm.toString(address(deployed.registry)),
                '","Escrow":"',
                vm.toString(address(deployed.escrow)),
                '","mUSDC":"',
                vm.toString(address(deployed.musdc)),
                '","mETH":"',
                vm.toString(address(deployed.meth)),
                '","STM":"',
                vm.toString(address(deployed.stm)),
                '","agents":{"Scout":"',
                vm.toString(agents.scout),
                '","Runner":"',
                vm.toString(agents.runner),
                '","Guardian":"',
                vm.toString(agents.guardian),
                '","Ledger":"',
                vm.toString(agents.ledger),
                '","Sentinel":"',
                vm.toString(agents.sentinel),
                '"}}'
            )
        );

        vm.writeJson(json, string.concat(vm.projectRoot(), "/docs/deployments.json"));
    }
}
