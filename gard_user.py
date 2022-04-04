# gard_user.py
# written by David McCabe
# Updated on 11/2/2021

'''
This program contains functions allowing: 
1. users to open/close new CDP positions 
2. users to redeem their GARD for their collateral 
3. users to mint more GARD from their open positions 
'''

# Imports
import base64
from algosdk import account, encoding, mnemonic
from algosdk.v2client import algod, indexer
from algosdk.future.transaction import PaymentTxn, LogicSig, LogicSigTransaction, AssetTransferTxn, calculate_group_id 
from algosdk.future.transaction import ApplicationCallTxn, ApplicationOptInTxn, ApplicationClearStateTxn
import msgpack
from time import sleep, time
from cdp_escrow import cdp
from reserve_logic import reserve
from pyteal import compileTeal, Mode

# Connects to testnet
# One can obtain a free API key from PureStake at https://developer.purestake.io/signup
def algod_client():
    algod_address = "https://testnet-algorand.api.purestake.io/ps2"
    algod_token = "sdhpfV7ILG2lQAVXpqgyQ8MnZx6mSm4L4EaSk7Ii"
    headers = {
       "X-API-Key": algod_token,
    }
    return algod.AlgodClient(algod_token, algod_address, headers)

# Helper function that waits for a given txid to be confirmed by the network
def wait_for_confirmation(client, txid):
    last_round = client.status().get('last-round')
    txinfo = client.pending_transaction_info(txid)
    while not (txinfo.get('confirmed-round') and txinfo.get('confirmed-round') > 0):
        print("Waiting for confirmation...")
        last_round += 1
        client.status_after_block(last_round)
        txinfo = client.pending_transaction_info(txid)
    print("Transaction {} confirmed in round {}.".format(txid, txinfo.get('confirmed-round')))
    return txinfo

# Closes position without paying closing fee 
# Only works if position was opened in the last 5 minutes
def close_cdp_no_fee(key, usr_addr, client, account_id, validator_id, debt, gard_id):

    # Transaction parameters
    params = client.suggested_params()
    params.flat_fee = True
    params.fee = 0

    program = reserve(gard_id)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = client.compile(compiled)
    reserve_addr = response['hash']

    # Calculate logic, address of CDP
    program = cdp(usr_addr, account_id)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = client.compile(compiled)
    program, contract_addr = response['result'], response['hash']

    # Create LogicSig
    prog = base64.decodebytes(program.encode())
    arg = (3).to_bytes(8, 'big')
    lsig = LogicSig(prog, args=[arg])

    reclaimed = client.account_info(contract_addr).get('amount')

    validator_args = ["CloseNoFee".encode()]
    # Construct Txns
    tx1 = ApplicationCallTxn(contract_addr, params, validator_id, 0, app_args=validator_args, accounts=[contract_addr], foreign_apps=[53083112], foreign_assets=[gard_id])
    params.fee = 4000
    tx2 = AssetTransferTxn(usr_addr, params, reserve_addr, debt, gard_id)
    params.fee = 0
    tx3 = ApplicationClearStateTxn(contract_addr, params, validator_id)
    tx4 = PaymentTxn(contract_addr, params, usr_addr, reclaimed, close_remainder_to=usr_addr)

     # Assign group id
    grp_id = calculate_group_id([tx1, tx2, tx3, tx4])
    tx1.group = grp_id
    tx2.group = grp_id
    tx3.group = grp_id
    tx4.group = grp_id

    # Sign & Submit
    stx1 = LogicSigTransaction(tx1, lsig)
    stx2 = tx2.sign(key)
    stx3 = LogicSigTransaction(tx3, lsig)
    stx4 = LogicSigTransaction(tx4, lsig)

    signed_group = [stx1, stx2, stx3, stx4]
    txid = client.send_transactions(signed_group)
    wait_for_confirmation(client, txid)
    

# Closes position and pays closing fee 
def close_cdp_fee(key, usr_addr, client, account_id, validator_id, debt, curr_price, fee_id, devfee_addr, gard_id):

    # Transaction parameters
    params = client.suggested_params()
    params.flat_fee = True
    params.fee = 0

    program = reserve(gard_id)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = client.compile(compiled)
    reserve_addr = response['hash']

    # Calculate logic, address of CDP
    program = cdp(usr_addr, account_id)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = client.compile(compiled)
    program, contract_addr = response['result'], response['hash']

    # Create LogicSig
    prog = base64.decodebytes(program.encode())
    arg = (2).to_bytes(8, 'big')
    lsig = LogicSig(prog, args=[arg])

    reclaimed = client.account_info(contract_addr).get('amount')
    fee = int(debt/(50*curr_price)) 
    fee += 10000

    validator_args = ["CloseFee".encode()]
    # Construct Txns
    tx1 = ApplicationCallTxn(contract_addr, params, validator_id, 0, app_args=validator_args, accounts=[contract_addr], foreign_apps=[53083112, fee_id], foreign_assets=[gard_id])
    params.fee = 5000
    tx2 = AssetTransferTxn(usr_addr, params, reserve_addr, debt, gard_id)
    params.fee = 0
    tx3 = ApplicationClearStateTxn(contract_addr, params, validator_id)
    tx4 = PaymentTxn(contract_addr, params, devfee_addr, fee, close_remainder_to=usr_addr)

    # Assign group id
    grp_id = calculate_group_id([tx1, tx2, tx3, tx4])
    tx1.group = grp_id
    tx2.group = grp_id
    tx3.group = grp_id
    tx4.group = grp_id

    # Sign & Submit
    stx1 = LogicSigTransaction(tx1, lsig)
    stx2 = tx2.sign(key)
    stx3 = LogicSigTransaction(tx3, lsig)
    stx4 = LogicSigTransaction(tx4, lsig)

    signed_group = [stx1, stx2, stx3, stx4]
    txid = client.send_transactions(signed_group)
    wait_for_confirmation(client, txid)
    
# Opens a new position and mints GARD
def open_cdp(key, address, client, total_malgs, GARD, account_id, validator_id, curr_price, fee_id, devfee_address, gard_id):

    # Transaction parameters   ,
    params = client.suggested_params()
    params.flat_fee = True
    params.fee = 1000
            
    # Check if account holds GARD
    account_info = client.account_info(address)
    flag = False
    for scrutinized_asset in account_info['assets']:
        scrutinized_id = scrutinized_asset['asset-id']
        if (scrutinized_id == gard_id):
            flag = True
            break

    # Calculate contract address
    program = cdp(address, account_id)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = client.compile(compiled)
    program, contract_addr = response['result'], response['hash']

    # Construct LogicSig
    prog = base64.decodebytes(program.encode())
    arg = (4).to_bytes(8, 'big')
    lsig = LogicSig(prog, args=[arg])

    params.fee = 2000
    txn1 = PaymentTxn(address, params, contract_addr, 300000)
    params.fee = 0
    txn2 = ApplicationOptInTxn(contract_addr, params, validator_id)
    if not flag:
        params.fee = 1000
        txn3 = AssetTransferTxn(address, params, address, 0, gard_id)
        note = "I'm opting in!".encode()
        g_id = calculate_group_id([txn1, txn2, txn3])
        txn1.group = g_id
        txn2.group = g_id
        txn3.group = g_id
        stx1 = txn1.sign(key)
        stx2 = LogicSigTransaction(txn2, lsig)
        stx3 = txn3.sign(key)
        signed_group = [stx1, stx2, stx3]
        txid = client.send_transactions(signed_group)
        wait_for_confirmation(client, txid)
        print("Contract opted into App + User opted into Stable")
    else:
        g_id = calculate_group_id([txn1, txn2])
        txn1.group = g_id
        txn2.group = g_id
        stxn1 = txn1.sign(key)
        stxn2 = LogicSigTransaction(txn2, lsig)
        signed_group = [stxn1, stxn2]
        txid = cl.send_transactions(signed_group)
        wait_for_confirmation(cl, txid)
        print("Contract opted into App")

    program = reserve(gard_id)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = client.compile(compiled)
    program, reserve_addr = response['result'], response["hash"]
    logic = base64.decodebytes(program.encode())
    arg = (1).to_bytes(8, 'big')
    lsig = LogicSig(logic, [arg])
    
    devfees = int(GARD/(50*curr_price)) 
    devfees += 10000

    # Construct Txns
    params.fee = 0
    validator_args = ["NewPosition".encode(), (int(time())).to_bytes(8, 'big')]
    tx1 = ApplicationCallTxn(address, params, validator_id, 0, app_args=validator_args, accounts=[contract_addr], foreign_apps=[53083112, fee_id], foreign_assets=[gard_id, account_id])
    params.fee = 4000
    tx2 = PaymentTxn(address, params, contract_addr, total_malgs)
    params.fee = 0
    tx3 = PaymentTxn(address, params, devfee_address, devfees)
    tx4 = AssetTransferTxn(reserve_addr, params, address, GARD, gard_id)

    # Assign group id
    grp_id = calculate_group_id([tx1, tx2, tx3, tx4])
    tx1.group = grp_id
    tx2.group = grp_id
    tx3.group = grp_id
    tx4.group = grp_id

    # Sign 
    stx1 = tx1.sign(key)
    stx2 = tx2.sign(key)
    stx3 = tx3.sign(key)
    stx4 = LogicSigTransaction(tx4, lsig)
    
    # Submit
    signed_group = [stx1, stx2, stx3, stx4]
    txid = client.send_transactions(signed_group)
    wait_for_confirmation(client, txid)
    # print("WooHoo! " + str(GARD) + " transferred to user!")

# Mints more GARD using an open position as collateral
def mint_from_existing(key, address, client, account_id, validator_id, to_mint, fee_id, devfee_address, gard_id):

    # Transaction parameters   ,
    params = client.suggested_params()
    params.flat_fee = True
    params.fee = 1000
 
    devfees = int(to_mint/(50*curr_price)) 
    devfees += 10000

    # Calculate contract address
    program = cdp(address, account_id)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = client.compile(compiled)
    program, contract_addr = response['result'], response['hash']

    # Construct LogicSig
    prog = base64.decodebytes(program.encode())
    arg = (5).to_bytes(8, 'big')
    lsig = LogicSig(prog, args=[arg])

    program = reserve(gard_id)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = client.compile(compiled)
    program, reserve_addr = response['result'], response["hash"]
    logic = base64.decodebytes(program.encode())
    arg = (2).to_bytes(8, 'big')
    lsig2 = LogicSig(logic, [arg])
       
    # Construct Txns
    params.fee = 0
    validator_args = ["MoreGARD".encode()]
    tx1 = ApplicationCallTxn(contract_addr, params, validator_id, 0, app_args=validator_args, accounts=[contract_addr], foreign_apps=[53083112, fee_id], foreign_assets=[gard_id])
    params.fee = 3000
    tx2 = PaymentTxn(address, params, devfee_address, devfees)
    params.fee = 0
    tx3 = AssetTransferTxn(reserve_addr, params, address, to_mint, gard_id)

    # Assign group id
    grp_id = calculate_group_id([tx1, tx2, tx3])
    tx1.group = grp_id
    tx2.group = grp_id
    tx3.group = grp_id

    # Sign 
    stx1 = LogicSigTransaction(tx1, lsig)
    stx2 = tx2.sign(key)
    stx3 = LogicSigTransaction(tx3, lsig2)
    
    # Submit
    signed_group = [stx1, stx2, stx3]
    txid = client.send_transactions(signed_group)
    wait_for_confirmation(client, txid)
    # print("WooHoo! " + str(to_mint) + " transferred to user!")

# Used to send voting transactions from the CDP
def cdp_vote(key, usr_addr, client, account_id):

    # Transaction parameters   
    params = client.suggested_params()
    params.flat_fee = True
    params.fee = 2000

    # Get Logic for CDP
    program = cdp(usr_addr, account_id)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = client.compile(compiled)
    program, contract_addr = response['result'], response['hash']

    # Construct LogicSig
    prog = base64.decodebytes(program.encode())
    arg = (0).to_bytes(8, 'big')
    lsig = LogicSig(prog, args=[arg])

    # Construct Txns
    tx1 = PaymentTxn(usr_addr, params, usr_addr, account_id)
    params.fee = 0
    note = "Heyo World!".encode()
    tx2 = PaymentTxn(contract_addr, params, usr_addr, 0, note=note)

    # Assign group id
    grp_id = calculate_group_id([tx1, tx2])
    tx1.group = grp_id
    tx2.group = grp_id

    # Sign & Submit
    stx1 = tx1.sign(key)
    stx2 = LogicSigTransaction(tx2, lsig)

    signed_group = [stx1, stx2]
    txid = cl.send_transactions(signed_group)
    wait_for_confirmation(cl, txid)
    
# Feel free to use this account or any other one with algos on the testnet
# Account info & Algod client
phrase = ""
key, address = mnemonic.to_private_key(phrase), mnemonic.to_public_key(phrase)
cl = algod_client()
validator_id = 58427084
open_app_id = 58426921
closing_app_id = 58426936
devfee_addr = "XFQGRTPRRZF632IUE7UNTAHXI43YYLFC3LGWM5WFT7JIXJHSSQW5GLY74E"
gard_id = 58426978
curr_price = 1.5951

def test1():
    account_id = 22

    print("Let's open, mint more, vote, and close without a fee :)")
    open_cdp(key, address, cl, 4333316, 1625671, account_id, validator_id, curr_price, open_app_id, devfee_addr, gard_id)

    mint_from_existing(key, address, cl, account_id, validator_id, 2000000, open_app_id, devfee_addr, gard_id)

    cdp_vote(key, address, cl, account_id)

    debt = 3625671
    close_cdp_no_fee(key, address, cl, account_id, validator_id, debt, gard_id)
    print("TEST 1 SUCCESS !!!")

def test2():
    account_id = 21

    print("Let's open, try to mint too much, then close with a fee")
    open_cdp(key, address, cl, 4333316, 1625671, account_id, validator_id, curr_price, open_app_id, devfee_addr, gard_id)

    try:
        mint_from_existing(key, address, cl, account_id, validator_id, 5000000)
        print("TEST FAILED")
    except:
        print("Transaction Rejected. As it should be :)")

    debt = 1625671
    close_cdp_fee(key, address, cl, account_id, validator_id, debt, curr_price, closing_app_id, devfee_addr, gard_id)
    print("TEST 2 SUCCESS !!!")

test1()
sleep(4)
test2()
    



