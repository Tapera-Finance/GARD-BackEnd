# create_reserve.py
# written by David McCabe
# on 11/2/2021

'''
This file contains the code for actually creating the GARD
tokens and transferring them to the reserve. Once it is run, it doesn't
serve much purpose for interacting with GARD.
'''

# Imports
import base64
from algosdk import account, encoding, mnemonic
from algosdk.v2client import algod
from algosdk.future.transaction import PaymentTxn, LogicSig, LogicSigTransaction, AssetConfigTxn, AssetTransferTxn, calculate_group_id
from reserve_logic import reserve
from cdp_escrow import cdp
from pyteal import compileTeal, Mode
from utils import algod_client, wait_for_confirmation

# Creates GARD ASA, returns created asset id
def create_token(key, address):
    
    # Create a client
    cl = algod_client()

    # Transaction Parameters
    params = cl.suggested_params()
    params.fee = 1000
    params.flat_fee = True

    # ASA info and txn construction
    txn = AssetConfigTxn(sender=address, sp=params, total=18400000000000000000, default_frozen=False, 
    unit_name="GARD", asset_name="GARD", manager = address, reserve=address, url="https://storage.googleapis.com/algo-pricing-data-2022/gard.json#arc3", 
    metadata_hash=b'\xb4Tkc;=\xdb\x9e@\xf5\x9btW\xef\x81J\xaeL\xc6\x13\xf3\xe3v\xbd=[\xe2\x15\xd9KQ\xb6', decimals=6, strict_empty_address_check=False)

    # Sign & Submit
    '''
    signed = txn.sign(key)
    txid = cl.send_transaction(signed)
    wait_for_confirmation(cl, txid)

    # Retrieves and returns asset id of created ASA
    try:
        ptx = cl.pending_transaction_info(txid)
        asset_id = ptx["asset-index"]
        ret = (asset_id)
    except Exception as e:
        print(e)
    '''
    return txn

def print_differences(stable_id, validator_id, devfee_addr):
    cl = algod_client()

    # Use this portion to get the template to be put into reserve_logic.py
    program = cdp("RHN53AKL3IJGOIF5BJTIUFDOH4KMPR45XS4JM63W46PWMFFR3PPZXF5DOQ", 12, stable_id, validator_id, devfee_addr)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = cl.compile(compiled)
    f = response["result"] 
    test = "Program".encode() + base64.decodebytes(f.encode())
    print("CDP Template: " + f)
    program = cdp("X3U6WGN4ZH4Z7HJMQ3ZYIPGEQSJK2XQW6RXQ35I4QSK5UZYN3JRJ3J74ZI", 116, stable_id, validator_id, devfee_addr)
    compiled = compileTeal(program, Mode.Signature, version=6)
    response = cl.compile(compiled)
    f = response["result"] 
    test1 = "Program".encode() + base64.decodebytes(f.encode()) 

    '''
    print(len(test), len(test1))
    for i in range(len(test)):
        if test[i] != test1[i]:
            print(i)
    '''

    # Used to see where differences are between template and custom contract
    if len(test) != 561 or len(test1) != len(test):
        raise RuntimeError("Incorrect template program length: " + str(len(test)))
    for i in range(len(test1)):
        if test1[i] != test[i] and (test[i-1] == test1[i-1] or test[i+1] == test1[i+1]):
            if i not in [30, 61, 455]:
                raise RuntimeError("Incorrect template values")
    return f
    


def finalize_reserve(stable_id, validator_id, devfee_addr, template, key, address):
    # Make a Client
    cl = algod_client()

    # Broadcast transaction parameters
    params = cl.suggested_params()
    params.flat_fee = True
    params.fee = 1000

    # Make Reserve account 
    program = reserve(stable_id, validator_id, devfee_addr, template)
    compiled = compileTeal(program, Mode.Signature, version=6)

    # Compile and get program logic and reserve address
    response = cl.compile(compiled)
    program, reserve_addr = response['result'], response['hash']
    print("Reserve Logic: " + program)
    # print(reserve_addr)

    # Convert to base64
    logic2_str = program.encode()
    logic2 = base64.decodebytes(logic2_str)
    print(len(logic2)) # Must be under 1000 bytes 

    # Fund Reserve
    unsigned_txn = PaymentTxn(address, params, reserve_addr, 201000)
    signed = unsigned_txn.sign(key)
    txid = cl.send_transaction(signed)
    wait_for_confirmation(cl, txid)

    # print("FUNDED!!!")

    # For saving and sending to user for logic signing
    # Record logic bytes 
    #with open("exchange.logic", "wb") as f:
    #    f.write(logic2_str)

    # Opt in Reserve for the created ASA
    arg1 = (0).to_bytes(8, 'big')
    lsig = LogicSig(logic2, [arg1])
    params.fee = 2000
    txn1 = PaymentTxn(address, params, address, 0)
    params.fee = 0
    txn2 = AssetTransferTxn(reserve_addr, params, reserve_addr, 0, stable_id)
    g_id = calculate_group_id([txn1, txn2])
    txn1.group = g_id
    txn2.group = g_id
    stxn1 = txn1.sign(key)
    stxn2 = LogicSigTransaction(txn2, lsig)
    signed_group = [stxn1, stxn2]
    txid = cl.send_transactions(signed_group)
    wait_for_confirmation(cl, txid)

    # print("Stable Opted")

    # Send Reserve/Treasury Account the supply of GARD
    params.fee = 1000
    txn1 = AssetTransferTxn(address, params, reserve_addr, 18400000000000000000//2, stable_id)
    txn2 = AssetTransferTxn(address, params, devfee_addr, 18400000000000000000//2, stable_id)

    gid = calculate_group_id([txn1, txn2])
    txn1.group = gid
    txn2.group = gid
    stxn1 = txn1.sign(key)
    stxn2 = txn2.sign(key)
    txid = cl.send_transactions([stxn1, stxn2])
    wait_for_confirmation(cl, txid)

    
    # print("Coins transferred!")

    # Set the token reserve to the reserve account
    txn1 = AssetConfigTxn(address, params, index=stable_id, manager="", reserve=reserve_addr, strict_empty_address_check=False)
    stxn1 = txn1.sign(key)
    txid = cl.send_transaction(stxn1)
    wait_for_confirmation(cl, txid)

    # print("Asset Config Updated")
