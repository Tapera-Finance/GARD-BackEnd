# GARD

## Description
This repository contains the Stateful Price Validator contract (price_validator.py), the Treasury Contract (treasury.py), and the reserve and CDP stateless contracts (cdp_escrow.py and reserve_logic.py). Additionally, there are DAO functionality contracts (Vote_fee.py, Stake.py, Vote_manager.py). Lastly, there two files for creating tokens (create_reserve.py, create_dao.py). DAO functionality consists of a devfee account controlled by the DAO, two fee-rate contracts, and a DAO manager election contract. There is also an old file with some functions for interacting with the GARD reserve (gard_user.py).

## Deployment 
1. Fill in the variable 'phrase' in app_setup.py with a 25-word mnemonic for an account with 10 algos on Testnet (see Account Creation and Funding)
2. Run app_setup.py 

## Account Creation and Funding
Code for creating new testnet accounts available here: https://developer.algorand.org/docs/features/accounts/create/#how-to-generate-a-standalone-account. Accounts on the testnet can be funded using the Algorand testnet bank: https://bank.testnet.algorand.network/.
