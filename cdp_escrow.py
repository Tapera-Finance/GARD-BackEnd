# cdp_escrow.py
# Written by David McCabe
# Updated on 12/23/2021

'''
This code holds the logic for a CDP Position.
The contract can be interacted with in 3 main ways:
1. Voting in Governance (so the account accrues interest)
2. Liquidation (by a "Keeper" when collateral value falls too low)
3. Redemption (by User when they want their collateral back)
'''

from pyteal import *

def cdp(user, cdp_id, stab_id, valid_id, devfee_add):

    user_address = Addr(user)

    stable_id = Int(stab_id)
    validator_id = Int(valid_id)
 
    devfee_address = Addr(devfee_add)

    # arg_id = 0
    # txn 0 -> self vote account
    # txn 1 -> payment txn of 0 
    Vote = And(
        Gtxn[0].amount() == Int(cdp_id),
        Gtxn[0].sender() == user_address,
        Gtxn[1].rekey_to() == Global.zero_address(),
        Gtxn[1].fee() == Int(0),
        If(Global.group_size() == Int(2)).Then(
            Or(
                And(
                Gtxn[1].type_enum() == TxnType.Payment,
                Gtxn[1].amount() == Int(0),
                Gtxn[1].close_remainder_to() == Global.zero_address()
            ),
                Gtxn[1].type_enum() == TxnType.KeyRegistration,
            )
        ).Else(
            And(
                Global.group_size() == Int(3),
                Gtxn[1].type_enum() == TxnType.ApplicationCall,
                Gtxn[1].application_id() != validator_id,
                Gtxn[2].application_id() == validator_id,
                Gtxn[2].on_completion() == OnComplete.NoOp,
                Gtxn[2].application_args[0] == Bytes("AppCheck"),
            )
        )
    )
    
    # To liquidate accounts with insufficient collateral
    # arg_id = 1
    # txn 0 -> Application call to price validator (application args["liquidate"])
    # txn 1 -> payment to buyer
    # txn 2 -> payment to reserve (in GARD)
    # txn 3 -> payment to devfee address (in GARD)
    # txn 4 -> payment to user address (in GARD)
    Liquidate = And(
        Global.group_size() == Int(5),
        Gtxn[0].on_completion() == OnComplete.CloseOut,
        Gtxn[0].application_id() == validator_id,
        Gtxn[0].assets[0] == stable_id,
        Gtxn[3].asset_receiver() == devfee_address,
        Gtxn[4].asset_receiver() == user_address
    )

    # For user to redeem outstanding stable tokens for collateral w/ fee
    # arg_id = 2
    # txn 0 -> Application call (application args[Bytes("CloseFee")])
    #                           (asset array args[stable_id])
    # txn 1 -> stable to reserve (from holder)
    # txn 2 -> Close out validator local state
    # txn 3 -> payment to fee account and the rest to user
    RedeemStableFee = And(
        Global.group_size() == Int(4),
        Gtxn[0].on_completion() == OnComplete.NoOp,
        Gtxn[0].application_id() == validator_id,
        Gtxn[0].application_args[0] == Bytes("CloseFee"),
        Gtxn[0].assets[0] == stable_id,
        Gtxn[1].sender() == user_address,
        Gtxn[2].on_completion() == OnComplete.ClearState,
        Gtxn[3].receiver() == devfee_address,
        Gtxn[3].close_remainder_to() == user_address,
    )

    # For user to redeem outstanding stable tokens for collateral w/out fee
    # arg_id = 3
    # txn 0 -> Application call (to obtain reserve address) (application args[Bytes("CloseNoFee")])
    #                           (asset array args[stable_id])
    # txn 1 -> stable to reserve (from holder)
    # txn 2 -> Close out validator local state
    # Txn 3 -> payment to holder
    RedeemStableNoFee = And(
        Global.group_size() == Int(4),
        Gtxn[0].on_completion() == OnComplete.NoOp,
        Gtxn[0].application_id() == validator_id, 
        Gtxn[0].application_args[0] == Bytes("CloseNoFee"),
        Gtxn[0].assets[0] == stable_id,
        Gtxn[1].sender() == user_address,
        Gtxn[2].on_completion() == OnComplete.ClearState,
    )

    # arg_id = 4
    Validator_OptIn = And(
        Txn.on_completion() == OnComplete.OptIn,
        Txn.application_id() == validator_id,
        Txn.rekey_to() == Global.zero_address(),
        Txn.fee() == Int(0)
    )

    # For user to mint more GARD leveraging the algo balance of the position
    # arg_id = 5
    # txn 0 -> Application call (application args[Bytes("MoreGARD)])
    #                           (asset array args[stable_id])
    # txn 1 -> devfee payment 
    # txn 2 -> GARD transfer to user
    More_gard = And(
        Global.group_size() == Int(3),
        Gtxn[0].on_completion() == OnComplete.NoOp,
        Gtxn[0].application_id() == validator_id, 
        Gtxn[0].application_args[0] == Bytes("MoreGARD"),
        Gtxn[1].sender() == user_address,
        Gtxn[1].receiver() == devfee_address
    )

    # arg_id = 6
    StartAuction = Or(
        And(
            Txn.application_id() == validator_id,
            Txn.on_completion() == OnComplete.NoOp,
            Txn.application_args[0] == Bytes("Auction"),
        ), 
        And(
            Global.group_size() == Int(3),
            Gtxn[0].application_id() == validator_id,
            Gtxn[0].on_completion() == OnComplete.NoOp,
            Gtxn[0].application_args[0] == Bytes("ClearApp"),
            Gtxn[1].on_completion() == OnComplete.ClearState
        )
    )

    # Only txns of one of the 7 types will be approved
    program = Cond(
        [Btoi(Arg(0)) == Int(0), Vote],
        [Btoi(Arg(0)) == Int(1), Liquidate],
        [Btoi(Arg(0)) == Int(2), RedeemStableFee],
        [Btoi(Arg(0)) == Int(3), RedeemStableNoFee],
        [Btoi(Arg(0)) == Int(4), Validator_OptIn],
        [Btoi(Arg(0)) == Int(5), More_gard],
        [Btoi(Arg(0)) == Int(6), StartAuction]
    )

    return program
    
