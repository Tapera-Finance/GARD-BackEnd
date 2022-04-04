# create_dao.py
# written by David McCabe
# on 1/11/2022

'''
This file contains the code for actually creating the GAIN (GARD DAO)
token and transferring them to the reserve. Once it is run, it doesn't
serve much purpose for interacting with the protocl.
'''

# Imports
import base64
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.future.transaction import AssetConfigTxn
from utils import algod_client, wait_for_confirmation

# Creates GARD ASA, returns created asset id
def create_dao_token(key, address):
    
    # Create a Client
    cl = algod_client()

    # Transaction Parameters
    params = cl.suggested_params()
    params.fee = 1000
    params.flat_fee = True

    # ASA info and txn construction
    txn = AssetConfigTxn(sender=address, sp=params, total=2000000000000000, default_frozen=False, 
    unit_name="GAIN", asset_name="GAIN", reserve=address, url="https://storage.googleapis.com/algo-pricing-data-2022/gain.json#arc3", 
    metadata_hash=b'\x0c\xfe\x0c\x83.u0\n\xbe\xaa\x12\x12\t\x99y\x1d$J\x08#v\xf3\x8d\xa3d\xa9SG\xeb(\x1e6', decimals=6, strict_empty_address_check=False)

    # Sign & Submit
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
    return ret

