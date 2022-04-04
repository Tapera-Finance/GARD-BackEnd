
import json, base64
from algosdk.v2client import algod
from algosdk import account, mnemonic, encoding
from algosdk.transaction import LogicSig, calculate_group_id, LogicSigTransaction
from algosdk.future.transaction import PaymentTxn, AssetTransferTxn, OnComplete
from pyteal import Mode, compileTeal, Seq, Int, InnerTxnBuilder, TxnField, \
	TxnType, Global, App, Bytes, Btoi, And, Gtxn, Subroutine, TealType, Expr, \
	Assert, Itob
	
# TODO: When done, split out the DAO utils from unused other utils
# TODO: At the very end, cleanup imports

def no_op_on_complete():
	return OnComplete.NoOpOC.real

# TEAL

@Subroutine(TealType.anytype)
def local_must_get(key, index, address) -> Expr:
    """Returns the result of a global storage MaybeValue if it exists, else Assert and fail the program"""
    maybe = App.localGetEx(address, index, key)
    return Seq(maybe, Assert(maybe.hasValue()), maybe.value())

@Subroutine(TealType.anytype)
def global_must_get(key, index) -> Expr:
    """Returns the result of a global storage MaybeValue if it exists, else Assert and fail the program"""
    maybe = App.globalGetEx(index, key)
    return Seq(maybe, Assert(maybe.hasValue()), maybe.value())
    
def increment_global(name, amount):
    return App.globalPut(name, App.globalGet(name) + amount)
    
def inner_asset_transfer(asset_id, amount, sender, receiver):
	return Seq(
		InnerTxnBuilder.Begin(),
		InnerTxnBuilder.SetFields({
			TxnField.type_enum: TxnType.AssetTransfer,
			TxnField.sender: sender,
			TxnField.asset_receiver: receiver,
			TxnField.xfer_asset: asset_id,
			TxnField.asset_amount: amount,
            TxnField.fee: Int(0)
		}),
		InnerTxnBuilder.Submit(),
	)
    
#    Conditions

def group_cond(i):
    # Checks if group size is i
    return Global.group_size() == Int(i)

def deposit_cond(txn_index, asset_id):
    return And(
        Gtxn[txn_index].type_enum() == TxnType.AssetTransfer,
        Gtxn[txn_index].xfer_asset() == asset_id
    )

def compile_teal(client, program, mode=Mode.Signature, version=4):
    compiled = compileTeal(program, mode, version=version)
    res = client.compile(compiled)
    ex_comp = base64.decodebytes(res['result'].encode())
    return ex_comp, {'pk': res['hash']}

# Connects to testnet
# One can obtain a free API key from PureStake at https://developer.purestake.io/signup
def algod_client():
    algod_address = "https://mainnet-algorand.api.purestake.io/ps2"
    # algod_address = "https://testnet-algorand.api.purestake.io/ps2"
    algod_token = ""
    headers = {
       "X-API-Key": algod_token,
    }
    return algod.AlgodClient(algod_token, algod_address, headers)
    
def get_params(client, fee=1000, flat_fee=True):
	params = client.suggested_params()
	params.fee = fee
	params.flat_fee = flat_fee
	return params

# Helper function that waits for a given txid to be confirmed by the network
def wait_for_confirmation(client, txid):
    last_round = client.status().get('last-round')
    txinfo = client.pending_transaction_info(txid)
    while not (txinfo.get('confirmed-round') and txinfo.get('confirmed-round') > 0):
      #  print("Waiting for confirmation...")
        last_round += 1
        client.status_after_block(last_round)
        txinfo = client.pending_transaction_info(txid)
    # print("Transaction {} confirmed in round {}.".format(txid, txinfo.get('confirmed-round')))
    return txinfo

def get_min_balance(client, address):
    info = client.account_info(address)
    return 101000 + (100000*(len(info["apps-local-state"])+len(info["assets"])+len(info["created-assets"])+len(info["created-apps"]))) + (50000*info["apps-total-schema"]["num-byte-slice"]) + (28500*info["apps-total-schema"]["num-uint"])

def send_wait_txn(client, stxn, task=None, multi=False):
	
	# XXX: Better would be type checking stxn as a list or not
	txid = None
	if not multi:
	    txid = client.send_transaction(stxn)
	else:
	    txid = client.send_transactions(stxn)
	
	message = "Sending tx w/ id " + txid
	if task:
		message += ", action: " + task
	# print(message)
	
	wait_for_confirmation(client, txid)
	
	return txid
	
def app_address(app_id):
	return encoding.encode_address(encoding.checksum(b'appID'+(app_id).to_bytes(8, 'big')))
	
def groupTxns(sender, *args):
	# Groups transactions
    gid = calculate_group_id(args)
    res = []
    for arg in args:
        arg.group = gid
        res.append(arg.sign(sender['key']))
    return res
