// SPDX-License-Identifier: MIT
pragma solidity ^0.8.4;

contract NFTOwnershipsReader {
    function getOwnerships(address target, uint256 begin, uint256 end) public view returns (address[] memory) {
        assembly {
            let m := mload(0x40)
            mstore(m, 0x20)
            mstore(add(m, 0x20), sub(end, begin))
            let o := add(m, 0x40)
            mstore(0x00, 0x6352211e) // `ownerOf(uint256)`.
            for { let id := begin } iszero(eq(id, end)) { id := add(1, id) } {
                mstore(0x20, id)
                mstore(o, mul(mload(0x20), staticcall(gas(), target, 0x1c, 0x24, 0x20, 0x20)))
                o := add(o, 0x20)
            }
            return(m, sub(o, m))
        }
    }
}