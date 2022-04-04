from utils import compile_teal, algod_client, no_op_on_complete, send_wait_txn
from Vote_lib import cancel_vote_check, init_vote_core, close_vote_core, \
	send_vote_core, current_stake
from algosdk.future.transaction import StateSchema, ApplicationCreateTxn, ApplicationNoOpTxn
from pyteal import *

# TODO: Go through and double check application array for including proper apps

# Constants
ASSET_TOTAL = Int(2000000000000000)
VOTE_INTERVAL = Int(7884000 - 86400)
VOTE_LENGTH = Int(86400)
MIN_VAL = 0
MAX_VAL = 30
STARTING_RESULT = Int(20)

def cancel_vote_seq(address):
	old_vote_choice = App.localGet(address, Bytes("Choice"))
	return Seq(
		App.globalPut(old_vote_choice, App.globalGet(old_vote_choice) - App.localGet(address, Bytes("Used_votes"))),
		App.localPut(address, Bytes("Vote_id"), Int(0)),
	)

def vote_program(staking_id, assetTotal=ASSET_TOTAL, \
				 vote_interval=VOTE_INTERVAL, vote_length=VOTE_LENGTH, \
				 min_val=Int(MIN_VAL), max_val=Int(MAX_VAL), starting_result=STARTING_RESULT):
	"""
	Voting contract for fee values.
	
	Votes are majority based, with majority being defined as a true
	majority (ie, 50% of all eligible votes + 1 vote), with all eligible votes
	being defined as the total supply of `asset_id`.
	
	Args:
		staking_id		(Int) - the app_id of the staking contract
		vote_interval	(Int) - the minimum length of time between votes
		vote_length		(Int) - the length of a vote
		min_val			(Int) - The minimum valid value
		max_val			(Int) - the largest number a vote can be
		starting_result (Int) - The starting result
	
	The following globals are used:
		Vote_end 	(Int) - the time a vote ends
		Vote_id 	(Int) - an id used for each vote
		Resolved	(Int) - whether a vote has been resolved
		Winner		(Int) - the last winner (or starting result, on init)
		min_val		(Int) - the minimum valid value
			...		(Int) - every integer between min_val and max_val
		max_val		(Int) - the maximum valid value
	
	The following local values are tracked:
		Vote_id		(Int) - the vote_id the users last vote was used for
		Choice		(Int) - the choice made in the vote
		Used_votes	(Int) - the amount of votes cast
	"""
	
	# Helpers
	i = ScratchVar(TealType.uint64)
	sender = Txn.sender()
	stake_app_id = Int(staking_id) # MAYBE: Remove this

	on_creation = Seq(
		# Sets up the contract, sets values that can't be 0
		App.globalPut(Bytes("Resolved"), Int(1)), # We start with the last "vote" as resolved, to allow new votes
		App.globalPut(Bytes("Winner"), starting_result),
		Approve(),
	)
		
	on_closeout = Seq(
		# Closes a user out - cancels their vote if there's an outstanding vote
		If(cancel_vote_check(sender), cancel_vote_seq(sender)),
		Approve()
	)
	
	# Voting
	@Subroutine(TealType.uint64)
	def valid_vote_check(vote):
		# Subroutine to check if a vote is done correctly
		vote_int = Btoi(vote)
		return And(
			min_val <= vote,
			vote <= max_val
		)
	
	# Voting: Sending a vote
	new_vote = Txn.application_args[1]
	send_vote = Seq(
		# Sends a vote
		# Args:
		#	[1] - the recipient of the new vote
		send_vote_core(valid_vote_check, new_vote, stake_app_id),
		App.globalPut(new_vote, App.globalGet(new_vote) + current_stake(stake_app_id, sender)),
		Approve(),
	)
	
	# Voting: Cancelling a vote
	cancel_vote = Seq(
		# Cancels a users last vote
		# Args:
		#	None
		Assert(cancel_vote_check(sender)),
		cancel_vote_seq(sender),
		Approve(),
	)
	
	# Voting: Changing a vote
	# change_vote - done by canceling then revoting
	
	# Voting: Initializes a vote
	init_vote = Seq(
		# Initializes a voting sequence
		# Args:
		#	None
		init_vote_core(vote_interval, vote_length),
		
		# Loops through all vote options and zeroes out
		For(i.store(Int(0)), i.load() <= max_val, i.store(i.load() + Int(1))).Do(
        		App.globalPut(Itob(i.load()), Int(0))
    	),
    		
		Approve(),
	)
	
	# Voting: Closing a vote
	close_vote = Seq(
		# Closes a voting sequence
		# Args:
		#	None
		close_vote_core(),
		
		# Loops through all vote options and finds the winner
		For(i.store(Int(0)), i.load() <= max_val, i.store(i.load() + Int(1))).Do(
			If(App.globalGet(Itob(i.load())) > (assetTotal / Int(2))).Then( # If the winner has more votes than the 50% of total DAO tokens
				Seq(
					App.globalPut(Bytes("Winner"), i.load()), # Store the winner
					Break(), # And break the loop
				)
			)
		),
		
		Approve(),
	)
	
	# Switch for choosing path
	program = Cond(
		[Txn.application_id() == Int(0), on_creation],
		[Txn.on_completion() == OnComplete.OptIn, Approve()],
		[Txn.on_completion() == OnComplete.DeleteApplication, Reject()],
		[Txn.on_completion() == OnComplete.UpdateApplication, Reject()],
		[Txn.on_completion() == OnComplete.CloseOut, on_closeout],
		[Txn.application_args[0] == Bytes("Vote"), send_vote],
		[Txn.application_args[0] == Bytes("Cancel"), cancel_vote],
		[Txn.application_args[0] == Bytes("Init"), init_vote],
		[Txn.application_args[0] == Bytes("Close"), close_vote],
	)
	
	return program

def fee_clear_state():
	# Cancels a user vote before clearing state to prevent exploits
	sender = Txn.sender()
	return Seq(
		If(cancel_vote_check(sender), cancel_vote_seq(sender)),
		Approve()
	)

def send_vote(client, sender, app_id, vote):
	params = client.suggested_params()
	txn = ApplicationNoOpTxn(sender['address'], params, app_id, ["Vote", vote])
	stxn = txn.sign(sender['key'])
	return send_wait_txn(client, stxn)


def create(client, sender, staking_id, min_val=MIN_VAL, max_val=MAX_VAL):
	# Deploys and creates the app

	# Establishes schema
	local_ints = 3
	local_bytes = 0
	global_ints = max_val - min_val + 1
	if global_ints > 64:
		raise # Could raise a more detailed error
	global_bytes = 0
	global_schema = StateSchema(global_ints, global_bytes)
	local_schema = StateSchema(local_ints, local_bytes)
	
	# Compiles
	main_program, _ = compile_teal(client, vote_program(staking_id, min_val=Int(min_val), max_val=Int(max_val)), mode=Mode.Application, version=6)
	clear_program, _ = compile_teal(client, fee_clear_state(), mode=Mode.Application, version=6)
	
	# Creates and sends the txn
	params = client.suggested_params()
	txn = ApplicationCreateTxn(sender['address'], params, no_op_on_complete(), main_program, clear_program, global_schema, local_schema)
	# stxn = txn.sign(sender['key'])
	# send_wait_txn(client, stxn)
	# app_id = client.pending_transaction_info(stxn.get_txid())["application-index"]
	
	return txn
