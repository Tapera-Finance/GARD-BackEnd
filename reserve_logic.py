# reserve_logic.py
# Written by David McCabe
# Updated on 12/23/2021

'''
This file holds the logic for the minting of new GARD
a valid minting amount comes from a reserve oracle
'''

from pyteal import *

# Takes uint64 and returns it as uvarint array
@Subroutine(TealType.bytes)
def Itovi(num):
    output = ScratchVar(TealType.bytes)
    temp = ScratchVar(TealType.uint64)
    main = Seq([
        output.store(Substring(Itob(num), Int(7), Int(8))),
        If(num >= Int(128)).Then(
            Seq([
                temp.store(num / Int(128)),
                While(temp.load() >= Int(128)).Do(
                Seq([
                    output.store(Concat(output.load(), Substring(Itob(temp.load()), Int(7), Int(8)))),
                    temp.store(temp.load() >> Int(7))
                    ])),
                output.store(Concat(output.load(), Substring(Itob(temp.load()), Int(7), Int(8))))
            ]))
    ])
    return Seq([main, Return(output.load())])

def reserve(stable_id, valid_id, devfee_add, template):

    # public key of DAO Devfee address
    devfee_address = Addr(devfee_add)

    validator_id = Int(valid_id)

    # template base64 encoding from compiling cdp("RHN53AKL3IJGOIF5BJTIUFDOH4KMPR45XS4JM63W46PWMFFR3PPZXF5DOQ", 12)
    # from cdp_escrow.py
    # address will be replaced with user address
    contract_logic = template
    
    y = Concat(Bytes("Program"), Bytes("base64", contract_logic))

    x1 = Substring(y, Int(0), Int(30))
    x2 = Substring(y, Int(62), Int(455)) 
    x3 = Substring(y, Int(456), Int(561))

    contract_addr = Sha512_256(Concat(x1, Gtxn[0].sender(), x2, Itovi(Gtxn[0].assets[1]), x3))

    # For Opt-in to GARD 
    # arg_id = 0
    optInStable = And(
        Txn.type_enum() == TxnType.AssetTransfer,
        Txn.xfer_asset() == Int(stable_id),
        Txn.asset_amount() == Int(0),
        Txn.rekey_to() == Global.zero_address(),
        Txn.asset_close_to() == Global.zero_address(),
        Txn.fee() == Int(0)
    )

    # For opening new position 
    # arg_id = 1
    # txn 0 -> Call to price validator (application args["NewPosition", Int(unix_start)]) all as bytes
    # account array [sender, contract_address] 
    # txn 1 -> proper algos to contract address (pays fee)
    # txn 2 -> Algo transfer to Tapera Fee account
    # txn 3 -> GARD transfer to User
    Core = And(
        Global.group_size() == Int(4),
        Gtxn[0].on_completion() == OnComplete.NoOp,
        Gtxn[0].application_id() == validator_id, 
        Gtxn[0].application_args[0] == Bytes("NewPosition"),
        Gtxn[0].accounts[1] == Gtxn[1].receiver(),
        Gtxn[0].assets[0] == Int(stable_id),
        Gtxn[1].type_enum() == TxnType.Payment,
        Gtxn[1].sender() == Gtxn[0].sender(),
        # contract address computed by filling in template
        Gtxn[1].receiver() == contract_addr,
        Gtxn[2].type_enum() == TxnType.Payment,
        # Gtxn[2].amount() is Checked by ApplicationCall
        Gtxn[2].sender() == Gtxn[1].sender(),
        Gtxn[2].receiver() == devfee_address,
        Gtxn[3].type_enum() == TxnType.AssetTransfer,
        Gtxn[3].xfer_asset() == Int(stable_id),
        Gtxn[3].fee() == Int(0),
        # Amount of GARD to be minted
        Gtxn[3].asset_close_to() == Global.zero_address(),
        Gtxn[3].rekey_to() == Global.zero_address(),

    )

    # For minting more from an open position
    more_gard = And(
        Global.group_size() == Int(3),
        Gtxn[0].on_completion() == OnComplete.NoOp,
        Gtxn[0].application_id() == validator_id, 
        Gtxn[0].application_args[0] == Bytes("MoreGARD"),
        Gtxn[0].assets[0] == Int(stable_id),
        Gtxn[2].type_enum() == TxnType.AssetTransfer,
        Gtxn[2].fee() == Int(0),
        Gtxn[2].asset_close_to() == Global.zero_address(),
        Gtxn[2].rekey_to() == Global.zero_address(),
    )

    # Approved Txns must be one of the 3 types
    program = Cond(
        [Btoi(Arg(0)) == Int(0), optInStable],
        [Btoi(Arg(0)) == Int(1), Core],
        [Btoi(Arg(0)) == Int(2), more_gard]
        )

    return program
