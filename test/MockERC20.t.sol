// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MockERC20} from "../src/mocks/MockERC20.sol";
import {TestBase} from "./TestBase.sol";

contract MockERC20Test is TestBase {
    MockERC20 private token;
    address private constant USER = address(0x4001);
    address private constant RECIPIENT = address(0x4002);

    function setUp() public {
        token = new MockERC20("Mock USDC", "mUSDC");
        token.mint(USER, 100 ether);
    }

    function testMintAndTransfer() public {
        assertEq(token.balanceOf(USER), 100 ether);

        vm.prank(USER);
        token.transfer(RECIPIENT, 40 ether);

        assertEq(token.balanceOf(USER), 60 ether);
        assertEq(token.balanceOf(RECIPIENT), 40 ether);
    }
}
