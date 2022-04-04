#!/usr/bin/env python3

# validator_test.py
# Written by David McCabe
# on 12/24/21

import base64
from algosdk import encoding, mnemonic
from algosdk.v2client import algod
from algosdk.future.transaction import PaymentTxn, LogicSig, ApplicationCreateTxn, ApplicationCallTxn, StateSchema, OnComplete, calculate_group_id
from price_validator import approval_program, clear_state_program
from treasury import treasury_approval, treasury_clear_state
from Stake import create as create_staking
from Stake import activate as activate_staking
from Vote_fee import create as create_fee
from Vote_manager import create as create_manager
from create_dao import create_dao_token
from create_reserve import create_token, print_differences, finalize_reserve
from pyteal import compileTeal, Mode, Int, Bytes
from utils import algod_client, wait_for_confirmation, send_wait_txn

def create_validator(cl, key, address, open_id, close_id, manager_id, stable_id):
    # declare application state storage (immutable)
    local_ints = 3
    local_bytes = 0
    global_ints = 2 
    global_bytes = 0
    global_schema = StateSchema(global_ints, global_bytes)
    local_schema = StateSchema(local_ints, local_bytes)

    # compile program to TEAL assembly
    compiled = compileTeal(approval_program(open_id, close_id, manager_id, stable_id), mode=Mode.Application, version=6)
    node_response = cl.compile(compiled)
    approval = base64.b64decode(node_response["result"])

    # compile program to TEAL assembly
    compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=6)
    node_response = cl.compile(compiled)
    clear_state = base64.b64decode(node_response["result"])

    # declare on_complete as NoOp
    on_complete = OnComplete.NoOpOC.real

    # get node suggested parameters
    params = cl.suggested_params()
    params.flat_fee = True
    params.fee = 1000

    # create unsigned transaction
    txn = ApplicationCreateTxn(address, params, on_complete, approval, 
                            clear_state, global_schema, local_schema)

    # sign & send transaction
    stxn = txn.sign(key)
    txid = cl.send_transaction(stxn)
    wait_for_confirmation(cl, txid)

    # display results
    transaction_response = cl.pending_transaction_info(txid)
    app_id = transaction_response['application-index']
    print("Validator app-id:", app_id)
    return app_id

def send_apps(stxns, cl):
    send_wait_txn(cl, stxns, multi=True)
    rets = []
    for i in range(3):
        rets.append(cl.pending_transaction_info(stxns[i].get_txid())["application-index"])
    rets.append(cl.pending_transaction_info(stxns[3].get_txid())["asset-index"])
    return rets

def create_treasury(cl, key, address, manager_id, stable_id, dao_id, validator_id):
    # declare application state storage (immutable)
    local_ints = 0
    local_bytes = 0
    global_ints = 2 
    global_bytes = 0
    global_schema = StateSchema(global_ints, global_bytes)
    local_schema = StateSchema(local_ints, local_bytes)

    # compile program to TEAL assembly
    compiled = compileTeal(treasury_approval(manager_id, stable_id, dao_id, validator_id), mode=Mode.Application, version=6)
    node_response = cl.compile(compiled)
    approval = base64.b64decode(node_response["result"])

    # compile program to TEAL assembly
    compiled = compileTeal(treasury_clear_state(), mode=Mode.Application, version=6)
    node_response = cl.compile(compiled)
    clear_state = base64.b64decode(node_response["result"])

    # declare on_complete as NoOp
    on_complete = OnComplete.NoOpOC.real

    # get node suggested parameters
    params = cl.suggested_params()
    params.flat_fee = True
    params.fee = 1000

    # create unsigned transaction
    txn = ApplicationCreateTxn(address, params, on_complete, approval, 
                            clear_state, global_schema, local_schema)

    # sign & send transaction
    stxn = txn.sign(key)
    txid = cl.send_transaction(stxn)
    wait_for_confirmation(cl, txid)

    # display results
    transaction_response = cl.pending_transaction_info(txid)
    app_id = transaction_response['application-index']
    print("Treasury app-id:", app_id)
    app_addr = encoding.encode_address(encoding.checksum(b'appID'+(app_id).to_bytes(8, 'big')))
    print("Treasury App Address: " + app_addr)

    txn = PaymentTxn(address, params, app_addr, 301000)
    stxn = txn.sign(key)
    txid = cl.send_transaction(stxn)
    wait_for_confirmation(cl, txid)
    return app_id, app_addr

def opt_app(client, key, address, app_id, token1_id, token2_id):
    # Transaction parameters   
    params = client.suggested_params()
    params.flat_fee = True
    params.fee = 3000
    app_args = ["Opt_In".encode()]

    tx1 = ApplicationCallTxn(address, params, app_id, 0, app_args=app_args, foreign_assets=[token1_id, token2_id])
    stx1 = tx1.sign(key)

    signed_group = [stx1]
    txid = client.send_transactions(signed_group)
    wait_for_confirmation(client, txid)
    
def main(key, address, user_key=None, user_address=None, liquid_key=None, liquid_address=None):
    cl = algod_client()
    sender = {
    	'key': key,
    	'address': address
    }
    msig = address # Fill this in later

    dao_id = create_dao_token(key, address)
    print("DAO asa-id: " + str(dao_id))
    staking_id = create_staking(cl, sender, dao_id)
    print("Staking app-id: " + str(staking_id))
    fee_txn1 = create_fee(cl, sender, staking_id)
    fee_txn2 = create_fee(cl, sender, staking_id)
    man_txn = create_manager(cl, sender, staking_id, init_manager=address) 
    token_txn = create_token(key, address) 
    gid = calculate_group_id([fee_txn1, fee_txn2, man_txn, token_txn])
    stxns = []
    for each in [fee_txn1, fee_txn2, man_txn, token_txn]:
        each.group = gid
        stxns.append(each.sign(key))
    open_id, close_id, manager_id, stable_id = send_apps(stxns, cl)
    print("Opening Fee app-id: " + str(open_id)) 
    print("Closing Fee app-id: " + str(close_id)) 
    print("Manager app-id: " + str(manager_id))
    print("Stable asa-id: " + str(stable_id))
    validator_id = create_validator(cl, key, address, open_id, close_id, manager_id, stable_id)
    treasury_id, treasury_addr = create_treasury(cl, key, address, manager_id, stable_id, dao_id, validator_id) 
    activate_staking(cl, sender, staking_id, manager_id, dao_id)
    opt_app(cl, key, address, treasury_id, stable_id, dao_id) 
    print("App Setup Complete!")
    template = print_differences(stable_id, validator_id, treasury_addr)
    finalize_reserve(stable_id, validator_id, treasury_addr, template, key, address)
    print("Reserve Setup Complete!")
    
if __name__ == "__main__":
    phrase = ""
    key, address = mnemonic.to_private_key(phrase), mnemonic.to_public_key(phrase)

    main(key, address)
