from utils import compile_teal, algod_client, \
	inner_asset_transfer, group_cond, \
	deposit_cond, global_must_get, no_op_on_complete, send_wait_txn, \
	groupTxns, app_address
from Vote_lib import has_voted, is_resolved, current_stake
from algosdk.future.transaction import StateSchema, ApplicationCreateTxn, ApplicationNoOpTxn, PaymentTxn, AssetTransferTxn
from pyteal import *

# TODO: Go through and double check application array for including proper apps

@Subroutine(TealType.uint64)
def no_vote(address, vote_i) -> Expr:
	# Checks if there is no active vote by `address` in vote contract at index `vote_i`
	app_id = App.globalGet(Itob(vote_i))
	return Or(
		is_resolved(app_id),
		Not(has_voted(address, app_id)),
	)
	
@Subroutine(TealType.uint64)
def check_all_votes(address) -> Expr:
	# Loops through and checks all votes for address
	i = ScratchVar(TealType.uint64)
	current_votes = App.globalGet(Bytes("Num_votes"))
	return Seq(
		For(i.store(Int(0)), i.load() < current_votes, i.store(i.load() + Int(1))).Do(
			If(Not(no_vote(address, i.load()))).Then(
				Return(Int(0))
			)
		),
		Return(Int(1))
	)

def close_out(address, asset_id):
	# Checks if `address` has no outstanding votes, then withdraws their stake if not.
	# Used to both close out and clear state
	return Seq(

		# Checks if there are no additional votes ongoing
		# XXX: A user must cancel all votes if they are to close out
		Assert(check_all_votes(address)),
		
		# Releases stake
		inner_asset_transfer(asset_id, App.localGet(address, Bytes("Stake")), Global.current_application_address(), address),
		
		Approve(),
	)

def stake_program(asset_id, launcher):
	"""
	Staking contract. Also points to all active votes.
	
	Args:
		asset_id - the asset used for staking/voting
		
	The following globals are used (64 ints):
		Num_votes (Int) - the number of active voting contracts
		Locked_votes (Int) - the number of locked in voting contracts
		0...60 (61x Ints) - mapping of i to the ith app_id handling the i_th voting contract
		Man_app_id (Int) - The app ID of the manager voting contract.
		
	The following local values are tracked:
		Stake (Int) - the size of the users stake
		DividendPeriod (Int) - the period in which the user last deposited stake OR claimed a dividend
			XXX: depositing more stake resets dividend period, which may make rewards unclaimable
	
	Future improvements may include
		- Designating someone to vote for you
			- This may be doable via a logical signature or something else

	XXX: There must be some care executed when removing voting contracts - with the way indexing is done,
		if there are any gaps in the mapping from int -> app_ids, this could cause issues. If a voting
		contract is removed, it must not be from a non-max index, *or* a vote_id with a higher index should
		be moved down to replace it.
	XXX: Locked_votes must be moved carefully, as this is a permanent variable that cannot be reduced. Use
		extreme caution if incrementing.
	"""
	
	isManager = Txn.sender() == global_must_get(Bytes("Manager"), App.globalGet(Bytes("Man_app_id")))
	
	# Adding voting contracts
	add_vote_app = Seq(
		# Adds a voting app, takes in the new address to add a voting app
		# XXX: Only the edge of the arrays can be added or removed from, use caution
		# Args:
		#	[1] (int) - the app_id of the new voting app
		Assert(isManager),
		# Adds the new contract
		App.globalPut(Itob(App.globalGet(Bytes("Num_votes"))), Btoi(Txn.application_args[1])),
		App.globalPut(Bytes("Num_votes"), App.globalGet(Bytes("Num_votes")) + Int(1)),
		Approve()
	)
	# Removing voting contracts
	remove_vote_app = Seq(
		# Removes the rightmost voting app (if eligible for removal)
		# XXX: Only the edge of the arrays can be added or removed from, use caution
		# Args:
		#	None
		Assert(And(
			isManager,
			App.globalGet(Bytes("Num_votes")) > Int(0),
			App.globalGet(Bytes("Locked_votes")) < App.globalGet(Bytes("Num_votes")), # Votes can't be removed if they are locked!
		)),
		# Simply decrements, since nothing should check the old address until replaced
		App.globalPut(Bytes("Num_votes"), App.globalGet(Bytes("Num_votes")) - Int(1)),
		Approve()
	)
	# Locks in key votes
	lock_vote_app = Seq(
		# Increments the index of the lowest locked in voting applications
		# XXX: Once an app is locked, there is no unlocking
		# Args:
		#	None
		Assert(isManager),
		App.globalPut(Bytes("Locked_votes"), App.globalGet(Bytes("Locked_votes")) + Int(1)),
		Approve()
	)
	
	# Helper
	sender = Txn.sender()

	# Staking/unstaking
	stake = Seq(
		# Adds to a users stake
		# Args:
		#	None (stake is sent in a paired transaction)
		
		Assert(
			And(
				group_cond(2), # group is sized 2
				deposit_cond(0, asset_id), # Gtxn[0] is an asset deposit
				Gtxn[0].asset_receiver() == Global.current_application_address(), # Recipient is this app
				Gtxn[0].sender() == sender, # The sender is the staker
			)
		),
		App.localPut(sender, Bytes("Stake"), current_stake(App.id(), sender) + Gtxn[0].asset_amount()),
		Approve(),
	)
	
	amount = Btoi(Txn.application_args[1])
	unstake = Seq(
		# Unstakes a users stake
		# Args:
		#	[1] (Int) - the amount a user wants to unstake
	
		Assert(
			And(
				amount <= current_stake(App.id(), sender), # Users stake is at most the amount they wish to withdraw
				check_all_votes(sender), # No active votes
			)
		),
		
		# Reduces stake
		App.localPut(sender, Bytes("Stake"), current_stake(App.id(), sender) - amount),
		# Releases stake
		inner_asset_transfer(asset_id, amount, Global.current_application_address(), sender),
		
		Approve(),
	)
	
	activate = Seq(
		# Adds the manager ID and opts into the proper token
		# Args:
		#	[1] (Int) - the manager app id
		Assert(And(
		 	App.globalGet(Bytes("Man_app_id")) == Int(0), # Manager_app must not be set
		 	sender == Addr(launcher)
		)),
		App.globalPut(Bytes("Man_app_id"), Btoi(Txn.application_args[1])),
		inner_asset_transfer(asset_id, Int(0), Global.current_application_address(), Global.current_application_address()),
		Approve()
	)
	
	program = Cond(
		[Txn.application_id() == Int(0), Approve()],
		[Txn.on_completion() == OnComplete.CloseOut, close_out(sender, asset_id)],
		[Txn.on_completion() == OnComplete.OptIn, Approve()],
		[Txn.on_completion() == OnComplete.DeleteApplication, Reject()],
		[Txn.on_completion() == OnComplete.UpdateApplication, Reject()],
		[Txn.application_args[0] == Bytes("Add_vote"), add_vote_app],
		[Txn.application_args[0] == Bytes("Remove_vote"), remove_vote_app],
		[Txn.application_args[0] == Bytes("Lock_vote"), lock_vote_app],
		[Txn.application_args[0] == Bytes("Stake"), stake],
		[Txn.application_args[0] == Bytes("Unstake"), unstake],
		[Txn.application_args[0] == Bytes("Activate"), activate],
	)
	
	return program
	
def stake_clear_state(asset_id):
	return close_out(Txn.sender(), asset_id)

def add_vote_app(client, sender, new_vote_app_id, app_id):
	params = client.suggested_params()
	txn = ApplicationNoOpTxn(sender['pk'], params, app_id, ["Add_vote", new_vote_app_id])
	stxn = txn.sign(sender['sk'])
	return send_wait_txn(client, stxn)

def remove_vote_app(client, sender, app_id):
	params = client.suggested_params()
	txn = ApplicationNoOpTxn(sender['pk'], params, app_id, ["Remove_vote"])
	stxn = txn.sign(sender['sk'])
	return send_wait_txn(client, stxn)

def lock_vote_app(client, sender, app_id):
	params = client.suggested_params()
	txn = ApplicationNoOpTxn(sender['pk'], params, app_id, ["Lock_vote"])
	stxn = txn.sign(sender['sk'])
	return send_wait_txn(client, stxn)

def stake(client, sender, app_id, asset_id, amount):

	# Transfers the DAO token
	params = client.suggested_params()
	transfer_txn = AssetTransferTxn(sender['address'], params, app_address(app_id), amount, asset_id)
	
	# Stakes
	params = client.suggested_params()
	stake_txn = ApplicationNoOpTxn(sender['pk'], params, app_id, ["Stake"])
	stxns = groupTxns(sender, transfer_txn, stake_txn)
	return send_wait_txn(client, stxn, multi=True)

def unstake(client, sender, app_id, amount):
	params = client.suggested_params()
	txn = ApplicationNoOpTxn(sender['address'], params, app_id, ["Unstake", amount])
	stxn = txn.sign(sender['key'])
	return send_wait_txn(client, stxn)

def activate(client, sender, app_id, manager_app_id, dao_token_id):
	# XXX: This must be called for proper functionality
	
	# Funds the account due to the activation
	params = client.suggested_params()
	fund_txn = PaymentTxn(sender['address'], params, app_address(app_id), 200000)
	
	# Activation includes an inner transaction, so you must pay 2x the fees needed
	params = client.suggested_params()
	params.flat_fee = True
	params.fee = 2000
	activate_txn = ApplicationNoOpTxn(sender['address'], params, app_id, ["Activate", manager_app_id], foreign_assets=[dao_token_id])
	stxns = groupTxns(sender, fund_txn, activate_txn)
	return send_wait_txn(client, stxns, multi=True)

def create(client, sender, asset_id):
	# Deploys and creates the app

	# Establishes schema
	local_ints = 2
	local_bytes = 0
	global_ints = 64
	global_bytes = 0
	global_schema = StateSchema(global_ints, global_bytes)
	local_schema = StateSchema(local_ints, local_bytes)
	
	# Compiles
	asset_id = Int(asset_id)
	main_program, _ = compile_teal(client, stake_program(asset_id, sender['address']), mode=Mode.Application, version=6)
	clear_program, _ = compile_teal(client, stake_clear_state(asset_id), mode=Mode.Application, version=6)
	
	# Creates and sends the txn
	params = client.suggested_params()
	txn = ApplicationCreateTxn(sender['address'], params, no_op_on_complete(), main_program, clear_program, global_schema, local_schema)
	stxn = txn.sign(sender['key'])
	send_wait_txn(client, stxn)
	app_id = client.pending_transaction_info(stxn.get_txid())["application-index"]
	
	return app_id

