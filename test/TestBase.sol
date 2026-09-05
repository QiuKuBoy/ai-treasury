// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface Vm {
    function deal(address account, uint256 newBalance) external;
    function expectRevert(bytes4 revertData) external;
    function prank(address msgSender) external;
}

abstract contract TestBase {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function assertEq(uint256 actual, uint256 expected) internal pure {
        require(actual == expected, "uint values differ");
    }

    function assertEq(address actual, address expected) internal pure {
        require(actual == expected, "address values differ");
    }

    function assertTrue(bool value) internal pure {
        require(value, "value is not true");
    }
}
