# price_validator.py
# Written by David McCabe
# on 12/23/2021

from pyteal import *
from utils import global_must_get

# Gets reserve address, if it exists of the first element of the foreign asset array
@Subroutine(TealType.bytes)
def get_reserve():
    x = ScratchVar(TealType.bytes)
    x = AssetParam.reserve(Int(0))
    main = Seq(
        x,
        Assert(x.hasValue()),
    )
    return Seq(main, Return(x.value()))

# Gets current price of collateral in the auction
# Decreases price linearly from 115% to 100% over 6 minutes
@Subroutine(TealType.uint64)
def auction_price():
    temp = ScratchVar(TealType.uint64)
    main = Seq(
        temp.store(App.localGet(Txn.sender(), Bytes("GARD_DEBT"))*Int(23)/Int(20)),
        If(Global.latest_timestamp() > App.localGet(Txn.sender(), Bytes("UNIX_START"))).Then(
            Seq(
                If(temp.load() > (App.localGet(Txn.sender(), Bytes("GARD_DEBT"))*(Global.latest_timestamp() - App.localGet(Txn.sender(), Bytes("UNIX_START")))/Int(2400))).Then(
                    Seq(
                        temp.store(temp.load()-(App.localGet(Txn.sender(), Bytes("GARD_DEBT"))*(Global.latest_timestamp() - App.localGet(Txn.sender(), Bytes("UNIX_START")))/Int(2400)))
                    )
                ).Else(
                    Seq(
                        temp.store(Int(0))
                    )
                )
            )
        )

    )
    return Seq(main, Return(temp.load()))

# Returns max of two numbers
@Subroutine(TealType.uint64)
def Max(a, b):
    return If(a > b, a, b)

def approval_program(open_id, close_id, manager_id, stable_id):

    # pricing data from Algoracle stateful contract
    # In USD/Algo
    price = global_must_get(Bytes("price"), Int(1)) 
    decimals = global_must_get(Bytes("decimals"), Int(1)) 

    # to be replaced by reference to DAO-controlled data
    open_fee = global_must_get(Bytes("Winner"), Int(2)) 
    closing_fee = global_must_get(Bytes("Winner"), Int(2))

    open_app_id = Int(open_id)
    closing_app_id = Int(close_id)
    price_app_id = global_must_get(Bytes("PRICING_APP_ID"), Int(0))

    manager_app_id = Int(manager_id)

    manager_account = global_must_get(Bytes("Manager"), Int(1))

    # Minutes until CDP must be closed with fee 
    no_fee_duration = Int(5)

    # Max number of external apps to opt into
    ex_apps_limit = Int(3)

    on_create = Seq(
        App.globalPut(Bytes("PRICING_APP_ID"), Int(673925841)),
        App.globalPut(Bytes("Original_Oracle"), Int(0)),
        Int(1)
    )

    start_auction = And(
        Txn.applications[1] == price_app_id,
        Txn.fee() == Int(0),
        Txn.rekey_to() == Global.zero_address(),
        # Generalizes equation with minimal division: 
        # 23/20 x GARD > collateral x (USD/mAlgo)
        App.localGet(Txn.sender(), Bytes("GARD_DEBT"))*Int(23)/Int(20) > Btoi(BytesDiv(BytesMul(Itob(Balance(Txn.sender())),Itob(price)),Itob(Int(10)**decimals))),
        Seq(
            Assert(App.localGet(Txn.sender(), Bytes("GARD_DEBT")) != Int(0)),
            # Round up to the nearest odd number
            App.localPut(Txn.sender(), Bytes("UNIX_START"), ((Global.latest_timestamp()/Int(2))*Int(2))+Int(1)),
            Int(1)
        )
    )

    # asset array args[stable_id]
    liquidate = And(
        Txn.rekey_to() == Global.zero_address(),
        Txn.assets[0] == Int(stable_id),
        Gtxn[1].rekey_to() == Global.zero_address(), # may be unnecessary since close_remainder_to must be set
        App.localGet(Txn.sender(), Bytes("UNIX_START")) % Int(2) == Int(1),
        # senders: 0 = 1, 2=3=4, 1 != 2
        Gtxn[0].sender() == Gtxn[1].sender(),
        Gtxn[1].sender() != Gtxn[2].sender(),
        Gtxn[2].sender() == Gtxn[3].sender(),
        Gtxn[3].sender() == Gtxn[4].sender(),
        Gtxn[1].type_enum() == TxnType.Payment,
        Gtxn[1].close_remainder_to() != Global.zero_address(),
        Gtxn[2].asset_receiver() == get_reserve(),
        Gtxn[2].asset_amount() + Gtxn[3].asset_amount() + Gtxn[4].asset_amount() >= Max(App.localGet(Txn.sender(), Bytes("GARD_DEBT")), auction_price()), 
        Gtxn[2].asset_amount() == App.localGet(Txn.sender(), Bytes("GARD_DEBT")),
        Gtxn[3].asset_amount() == Gtxn[4].asset_amount()/Int(4),
        Gtxn[3].xfer_asset() == Int(stable_id),
        Gtxn[4].xfer_asset() == Int(stable_id),
        Gtxn[0].fee() + Gtxn[1].fee() == Int(0),
        Seq(
            App.localDel(Txn.sender(), Bytes("GARD_DEBT")),
            App.localDel(Txn.sender(), Bytes("UNIX_START")),
            App.localDel(Txn.sender(), Bytes("EXTERNAL_APPCOUNT")),
            Int(1)
        )
    )
    
    # application args["CloseFee"]
    # (asset array args[stable_id])
    close_with_fee = And(
        Txn.applications[1] == price_app_id,
        Txn.applications[2] == closing_app_id,
        Txn.assets[0] == Int(stable_id),
        Txn.rekey_to() == Global.zero_address(),
        Gtxn[1].xfer_asset() == Gtxn[0].assets[0],
        Gtxn[2].rekey_to() == Global.zero_address(),
        Gtxn[3].rekey_to() == Global.zero_address(),
        Gtxn[1].asset_receiver() == get_reserve(),
        Gtxn[2].sender() == Gtxn[0].sender(),
        Gtxn[3].sender() == Gtxn[2].sender(),
        Gtxn[1].type_enum() == TxnType.AssetTransfer,
        Gtxn[3].type_enum() == TxnType.Payment,
        Gtxn[0].fee() + Gtxn[2].fee() + Gtxn[3].fee() == Int(0),
        Gtxn[0].application_id() == Gtxn[2].application_id(),
        Gtxn[1].asset_amount() == App.localGet(Txn.sender(), Bytes("GARD_DEBT")), 
        # fee >= GARD x (malgo/USD) x (fee_pct (two decimals) / 1000)
        Gtxn[3].amount() >= Btoi(BytesDiv(BytesMul(Itob(Gtxn[1].asset_amount()*closing_fee),Itob(Int(10)**decimals)), Itob(Int(1000)*price))),
    ) 

    # application args["CloseNoFee"]
    # (asset array args[stable_id])
    close_no_fee = And(
        Txn.rekey_to() == Global.zero_address(),
        Gtxn[1].xfer_asset() == Gtxn[0].assets[0],
        Txn.assets[0] == Int(stable_id),
        Gtxn[2].rekey_to() == Global.zero_address(),
        Gtxn[3].rekey_to() == Global.zero_address(),
        Global.latest_timestamp() <= App.localGet(Txn.sender(), Bytes("UNIX_START")) + (Int(60)*no_fee_duration),
        Gtxn[2].sender() == Gtxn[0].sender(),
        Gtxn[3].sender() == Gtxn[2].sender(),
        Gtxn[1].type_enum() == TxnType.AssetTransfer,
        Gtxn[3].type_enum() == TxnType.Payment,
        Gtxn[3].close_remainder_to() != Global.zero_address(),
        Gtxn[0].application_id() == Gtxn[2].application_id(),
        Gtxn[0].fee() + Gtxn[2].fee() + Gtxn[3].fee() == Int(0),
        Gtxn[1].asset_receiver() == get_reserve(),
        Gtxn[1].asset_amount() == App.localGet(Txn.sender(), Bytes("GARD_DEBT")),
    )

    # application args["NewPosition", Int(unix_start)]
    # (asset array args[stable_id, account_id])
    new_position = And(
        Txn.applications[1] == price_app_id,
        Txn.applications[2] == open_app_id,
        Txn.assets[0] == Int(stable_id),
        Txn.rekey_to() == Global.zero_address(),
        Global.latest_timestamp() <= Btoi(Gtxn[0].application_args[1]) + Int(30),
        Global.latest_timestamp() >= Btoi(Gtxn[0].application_args[1]) - Int(30),
        # Protects against overflow
        Gtxn[3].asset_amount() <= Int(60000000000000000),
        Gtxn[3].asset_amount() >= Int(1000000), 
        # fee >= GARD x (malgo/USD) x (fee_pct (two decimals) / 1000)
        Gtxn[2].amount() >= Btoi(BytesDiv(BytesMul(Itob(Gtxn[3].asset_amount()*open_fee),Itob(Int(10)**decimals)), Itob(Int(1000)*price))),
        # 7/5 x GARD <= collateral x (USD/mAlgo)
        Gtxn[3].asset_amount()*Int(7)/Int(5) <= Btoi(BytesDiv(BytesMul(Itob(Balance(Int(1)) + Gtxn[1].amount()),Itob(price)),Itob(Int(10)**decimals))),
        Seq(
            Assert(App.localGet(Int(1), Bytes("GARD_DEBT")) == Int(0)),
            Assert(get_reserve() == Gtxn[3].sender()),
            App.localPut(Int(1), Bytes("GARD_DEBT"), Gtxn[3].asset_amount()),
            # Round down to the nearest even number
            App.localPut(Int(1), Bytes("UNIX_START"), (Btoi(Gtxn[0].application_args[1])/Int(2))*Int(2)),
            App.localPut(Int(1), Bytes("EXTERNAL_APPCOUNT"), Int(0)),
            Int(1)
        ),
    )

    more_gard = And(
        Txn.applications[1] == price_app_id,
        Txn.applications[2] == open_app_id,
        Txn.assets[0] == Int(stable_id),
        Txn.rekey_to() == Global.zero_address(),
        App.localGet(Txn.sender(), Bytes("GARD_DEBT")) != Int(0),
        Gtxn[1].sender() != get_reserve(), 
        Gtxn[2].sender() == get_reserve(), 
        Gtxn[2].sender() != Gtxn[0].sender(),
        Txn.sender() == Gtxn[0].sender(),
        Gtxn[0].fee() == Int(0),
        Gtxn[2].asset_amount() >= Int(1000000),
        # Protects against overflow
        Gtxn[2].asset_amount() <= Int(600000000000000000) - App.localGet(Txn.sender(), Bytes("GARD_DEBT")),
        # fee >= GARD x (malgo/USD) x (fee_pct (two decimals) / 1000)
        Gtxn[1].amount() >= Btoi(BytesDiv(BytesMul(Itob(Gtxn[2].asset_amount()*open_fee),Itob(Int(10)**decimals)), Itob(Int(1000)*price))), 
        # 7/5 x GARD <= collateral x (USD/mAlgo)
        (App.localGet(Txn.sender(), Bytes("GARD_DEBT")) + Gtxn[2].asset_amount())*Int(7)/Int(5) <= Btoi(BytesDiv(BytesMul(Itob(Balance(Txn.sender())),Itob(price)),Itob(Int(10)**decimals))),
        Seq(
            App.localPut(Txn.sender(), Bytes("GARD_DEBT"), App.localGet(Txn.sender(), Bytes("GARD_DEBT"))+Gtxn[2].asset_amount()),
            Int(1)
        ),
    )

    app_check = And(
        Txn.rekey_to() == Global.zero_address(),
        Gtxn[2].sender() == Gtxn[1].sender(),
        App.localGet(Txn.sender(), Bytes("UNIX_START")) % Int(2) != Int(1),
        Gtxn[1].fee() + Gtxn[2].fee() == Int(0),
        App.localGet(Txn.sender(), Bytes("EXTERNAL_APPCOUNT")) < ex_apps_limit,
        Seq(
            App.localPut(Txn.sender(), Bytes("EXTERNAL_APPCOUNT"), App.localGet(Txn.sender(), Bytes("EXTERNAL_APPCOUNT")) + Int(1)),
            Int(1),
        ),

    )

    change_price = And(
        Txn.rekey_to() == Global.zero_address(),
        Txn.applications[1] == manager_app_id,
        Txn.sender() == manager_account,
        App.globalGet(Bytes("Original_Oracle")) <= Int(3),
        Seq(
            App.globalPut(Bytes("PRICING_APP_ID"), Btoi(Txn.application_args[1])),
            App.globalPut(Bytes("Original_Oracle"), App.globalGet(Bytes("Original_Oracle")) + Int(1)),
            Int(1)
        )
    )

    clear_app = And(
        Txn.accounts[1] == Gtxn[2].sender(),
        App.localGet(Int(1), Bytes("UNIX_START")) == Int(0),
        Txn.rekey_to() == Global.zero_address(),
        Gtxn[1].application_id() != Global.current_application_id(),
        Gtxn[1].rekey_to() == Global.zero_address(),
        Gtxn[2].sender() != Gtxn[0].sender(),
        Gtxn[1].sender() == Txn.sender(),
        Gtxn[0].fee() + Gtxn[1].fee() == Int(0),
        App.localGet(Txn.sender(), Bytes("UNIX_START")) % Int(2) == Int(1),   
    )

    return Cond(
        # On app creation
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.DeleteApplication, Int(0)],
        [Txn.on_completion() == OnComplete.UpdateApplication, Int(0)],
        [Txn.on_completion() == OnComplete.CloseOut, liquidate],
        [Txn.on_completion() == OnComplete.OptIn, Int(1)],
        # Must be a NoOp transaction
        [Txn.application_args[0] == Bytes("Auction"), start_auction],
        [Txn.application_args[0] == Bytes("CloseFee"), close_with_fee],
        [Txn.application_args[0] == Bytes("CloseNoFee"), close_no_fee],
        [Txn.application_args[0] == Bytes("NewPosition"), new_position],
        [Txn.application_args[0] == Bytes("MoreGARD"), more_gard],
        [Txn.application_args[0] == Bytes("AppCheck"), app_check],
        [Txn.application_args[0] == Bytes("ClearApp"), clear_app],
        [Txn.application_args[0] == Bytes("ChangePricing"), change_price]
    )

def clear_state_program():
    return Seq(
        App.localDel(Txn.sender(), Bytes("GARD_DEBT")),
        App.localDel(Txn.sender(), Bytes("UNIX_START")),
        Int(1)
        )
