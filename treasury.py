# treasury.py
# Written by David McCabe
# on 1/11/2022

from pyteal import *
from utils import global_must_get

def treasury_approval(manager_id, gard_id, dao_id, validator_id):

    stable_id = Int(gard_id)
    gain_id = Int(dao_id)

    # This must be updated before deployment
    initial_supply = Int(2000000000000000)

    price = global_must_get(Bytes("price"), Int(1)) 
    decimals = global_must_get(Bytes("decimals"), Int(1))

    price_app_id = global_must_get(Bytes("PRICING_APP_ID"), Int(validator_id))
    manager_app_id = Int(manager_id)

    manager_account = global_must_get(Bytes("Manager"), Int(2))

    # This account will change, the percentage might change
    founder_account = Addr("B7YLKLF7FGTURCSGOPO2GHTLEQKXEQHVTIMFOZWBYUY55RDGTADQDS3ICI")
    founder_percent = Int(2)

    # This account will change, the percentage might change
    manager_account = global_must_get(Bytes("Manager"), Int(2))
    manager_percent = Int(18)

    on_create = Seq(
        App.globalPut(Bytes("ALGO_BALANCE"), Int(0)),
        App.globalPut(Bytes("Latest"), Global.latest_timestamp()),
        Int(1)
    )

    opt_in = And(
        Global.latest_timestamp() <= Int(1658814885),
        Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.asset_receiver: Global.current_application_address(),
                    TxnField.xfer_asset: stable_id,
                    TxnField.asset_amount: Int(0),
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.asset_receiver: Global.current_application_address(),
                    TxnField.xfer_asset: gain_id,
                    TxnField.asset_amount: Int(0),
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
            Int(1)
        )
    )

    temp = ScratchVar(TealType.uint64)
    payout = And(
        # Ensures 3 months have passed 
        Global.latest_timestamp() - global_must_get(Bytes("Latest"), Int(0)) >= Int(7889400),
        Txn.applications[1] == manager_app_id, 
        # Ensures variables are set correctly for innertxns
        Txn.accounts[1] == Global.current_application_address(),
        Txn.assets[0] == stable_id,
        Seq( 
            App.globalPut(Bytes("Latest"), Global.latest_timestamp()),
            temp.store((Balance(Int(1))-App.globalGet(Bytes("ALGO_BALANCE")))*manager_percent/Int(100)),
            Int(1)
        ),
        Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: founder_account,
                    TxnField.amount: (Balance(Int(1))-App.globalGet(Bytes("ALGO_BALANCE")))*founder_percent/Int(100),
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: manager_account,
                    TxnField.amount: temp.load(),
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
            App.globalPut(Bytes("ALGO_BALANCE"), Balance(Int(1))),
            Int(1)
        )
    )

    gain_bal = AssetHolding.balance(Txn.accounts[1], Txn.assets[0])
    claim = And(
        Global.group_size() == Int(2),
        Gtxn[1].sender() == Txn.sender(),
        Gtxn[1].asset_amount() > Int(0),
        Gtxn[1].xfer_asset() == gain_id,
        Gtxn[1].asset_receiver() == Global.current_application_address(),
        Txn.accounts[1] == Global.current_application_address(),
        Txn.assets[0] == gain_id,
        Seq(
            gain_bal,
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: Txn.sender(),
                    TxnField.amount: Btoi(BytesDiv(BytesMul(Itob(Balance(Int(1))),Itob(Gtxn[1].asset_amount())),Itob(initial_supply-gain_bal.value()))),
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
            Int(1)
        )
    )

    ALGO_TO_GARD = And(
        Global.group_size() == Int(2),
        Txn.applications[1] == price_app_id,
        Txn.applications[2] == manager_app_id,
        Gtxn[1].type_enum() == TxnType.Payment,
        Gtxn[0].sender() == manager_account,
        Gtxn[1].sender() == Gtxn[0].sender(),
        Gtxn[1].receiver() == Global.current_application_address(),
        Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.asset_receiver: manager_account,
                    TxnField.asset_amount: Btoi(BytesDiv(BytesMul(Itob(Gtxn[1].amount()),Itob(Int(10)**decimals)), Itob(price))),
                    TxnField.xfer_asset: stable_id,
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
            Int(1)
        ),

    )

    GARD_TO_ALGO = And(
        Global.group_size() == Int(2),
        Txn.applications[1] == price_app_id,
        Txn.applications[2] == manager_app_id,
        Gtxn[1].type_enum() == TxnType.AssetTransfer,
        Gtxn[1].xfer_asset() == stable_id,
        Gtxn[0].sender() == manager_account,
        Gtxn[1].sender() == Gtxn[0].sender(),
        Gtxn[1].asset_receiver() == Global.current_application_address(),
        Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: manager_account,
                    TxnField.amount: Btoi(BytesDiv(BytesMul(Itob(Gtxn[1].asset_amount()),Itob(price)), Itob(Int(10)**decimals))),
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
            Int(1)
        )
    )    

    return Cond(
        # On app creation
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.DeleteApplication, Int(0)],
        [Txn.on_completion() == OnComplete.UpdateApplication, Int(0)],
        [Txn.on_completion() == OnComplete.CloseOut, Int(0)],
        [Txn.on_completion() == OnComplete.OptIn, Int(0)],
        # Must be a NoOp transaction
        [Txn.application_args[0] == Bytes("To_ALGO"), GARD_TO_ALGO],
        [Txn.application_args[0] == Bytes("To_GARD"), ALGO_TO_GARD],
        [Txn.application_args[0] == Bytes("Opt_In"), opt_in],
        [Txn.application_args[0] == Bytes("Claim"), claim],
        [Txn.application_args[0] == Bytes("Payout"), payout]
        
    )

def treasury_clear_state():
    return Seq(
        Int(1)
        )
