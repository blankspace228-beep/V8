// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Purple Coin (PPC)
/// @notice Fixed-supply ERC-20 contract intended for Purple Paper testnet validation first.
/// @dev No owner mint function exists. Exactly 10,000 PPC are created once at deployment.
contract PurpleCoin {
    string public constant name = "Purple Coin";
    string public constant symbol = "PPC";
    uint8 public constant decimals = 18;
    uint256 public constant totalSupply = 10_000 * 10 ** uint256(decimals);

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor(address initialHolder) {
        require(initialHolder != address(0), "zero holder");
        balanceOf[initialHolder] = totalSupply;
        emit Transfer(address(0), initialHolder, totalSupply);
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= value, "allowance");
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - value;
            emit Approval(from, msg.sender, allowance[from][msg.sender]);
        }
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "zero recipient");
        uint256 bal = balanceOf[from];
        require(bal >= value, "balance");
        unchecked { balanceOf[from] = bal - value; }
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }
}
