// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * CBDC (Central Bank Digital Currency) Token Contract
 * Supports: mint, transfer, burn, freeze — mimics real CBDC operations
 */
contract CBDC {
    string  public name     = "Digital Currency";
    string  public symbol   = "CBDC";
    uint8   public decimals = 18;

    address public centralBank;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => bool)    public frozen;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Mint(address indexed to, uint256 value);
    event Burn(address indexed from, uint256 value);
    event Freeze(address indexed account, bool status);

    modifier onlyCentralBank() {
        require(msg.sender == centralBank, "Not authorized");
        _;
    }

    modifier notFrozen(address account) {
        require(!frozen[account], "Account frozen");
        _;
    }

    constructor() {
        centralBank = msg.sender;
    }

    function mint(address to, uint256 amount) external onlyCentralBank {
        totalSupply       += amount;
        balanceOf[to]     += amount;
        emit Mint(to, amount);
        emit Transfer(address(0), to, amount);
    }

    function transfer(address to, uint256 amount)
        external
        notFrozen(msg.sender)
        notFrozen(to)
        returns (bool)
    {
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[to]         += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }

    function burn(address from, uint256 amount) external onlyCentralBank {
        require(balanceOf[from] >= amount, "Insufficient balance");
        balanceOf[from] -= amount;
        totalSupply     -= amount;
        emit Burn(from, amount);
        emit Transfer(from, address(0), amount);
    }

    function setFreeze(address account, bool status) external onlyCentralBank {
        frozen[account] = status;
        emit Freeze(account, status);
    }

    // Batch mint for benchmark seeding
    function batchMint(address[] calldata recipients, uint256 amount) external onlyCentralBank {
        for (uint i = 0; i < recipients.length; i++) {
            totalSupply           += amount;
            balanceOf[recipients[i]] += amount;
            emit Transfer(address(0), recipients[i], amount);
        }
    }
}
