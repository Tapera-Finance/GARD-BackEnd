from utils import compile_teal, algod_client, no_op_on_complete, send_wait_txn
from Vote_lib import cancel_vote_check, init_vote_core, \
	send_vote_core, close_vote_core, current_stake
from algosdk.future.transaction import StateSchema, ApplicationCreateTxn, ApplicationNoOpTxn
from pyteal import *

# Constants
VOTE_INTERVAL = Int(7884000 - 86400)
VOTE_LENGTH = Int(86400)
STARTING_MANAGER = Addr("2AJW53433XKGFNFS4GNRSWSVQ5NWT4QQGPWEETJ7DQZVW63OVHR3MK4PYQ")


def cancel_vote_seq(address):
	old_vote_choice = App.localGet(address, Bytes("Choice"))
	return Seq(
		App.localPut(old_vote_choice, Bytes("Vote_ct"), App.localGet(old_vote_choice, Bytes("Vote_ct")) - App.localGet(address, Bytes("Used_votes"))),
		App.localPut(address, Bytes("Vote_id"), Int(0)),
	)

def manager_approval(staking_id, vote_interval=VOTE_INTERVAL, vote_length=VOTE_LENGTH, init_manager=STARTING_MANAGER):
	"""
	Voting contract for the manager address.
	
	The winner is the address with the highest vote counts.
	
	Args:
		staking_id		(Int) - the app_id of the staking contract
		vote_interval	(Int) - the minimum length of time between votes TODO: In seconds? ms?
		vote_length		(Int) - the length of a vote
		init_manager	(Bytes) - the starting manager
	
	The following globals are used:
		Vote_end	(Int) - the time a vote ends
		Vote_id		(Int) - an id used for each vote
		Manager		(Bytes) - the active manager
		Vote_leader	(Bytes) - the current leader
		Resolved	(Int) - whether a vote has been resolved
	
	The following local values are tracked:
		Vote_id		(Int) - the vote_id the users last vote was used for
		Choice		(Bytes) - the choice made in the vote
		Vote_ct		(Int) - the votes a user has
		Vote_ct_id	(Int) - the vote_id of the count
		Used_votes	(Int) - the total votes cast by the user
	
		
	XXX: As this is setup - something weird can happen, where theoretically, the current winner could
		go from first place to not first place if a user cancels their vote. If no one cast a vote for
		the new winner, then the (no-longer) highest vote getter would be deemed the winner
		
		Solution: This can be solved by having a daemon run and watching all transactions with
			the app. The daemon can keep a tally of all vote recipients totals, and, if someone
			who is not actually in first place is marked as the Vote_leader, the daemon could
			send a vote of 0 for the actual winner, which will correct the value stored in
			Vote_leader. Note that any number of daemons could be run by any number of parties,
			ensuring trustful execution of the vote.
	"""
	
	# Helpers
	sender = Txn.sender()
	stake_app_id = Int(staking_id) # MAYBE: Remove this conversion

	on_creation = Seq(
		# Sets up the contract, sets values that can't be 0
		App.globalPut(Bytes("Resolved"), Int(1)), # We start with the last "vote" as resolved, to allow new votes
		App.globalPut(Bytes("Manager"), init_manager),
		
		Approve(),
	)
	
	# Closeout
	on_closeout = Seq(
		If(cancel_vote_check(sender), cancel_vote_seq(sender)),
		Approve()
	)
	
	# Voting: Sending a vote
	new_vote = Txn.application_args[1]
	@Subroutine(TealType.uint64)
	def valid_vote_check(vote):
		# Any vote is valid, users should be careful when sending a vote
		return Int(1)
	send_vote = Seq(
		# Sends a vote
		# Args:
		#	[1] (bytes) - the recipient of the new vote
		send_vote_core(valid_vote_check, new_vote, stake_app_id),
		
		# Checks if the choice's current vote total is for the proper Vote_id if not, it resets it
		If(App.localGet(new_vote, Bytes("Vote_ct_id")) != App.globalGet(Bytes("Vote_id"))).Then(Seq(
			App.localPut(new_vote, Bytes("Vote_ct_id"), App.globalGet(Bytes("Vote_id"))),
			App.localPut(new_vote, Bytes("Vote_ct"), Int(0))
		)),
		
		# Increments the vote count
		App.localPut(new_vote, Bytes("Vote_ct"), App.localGet(new_vote, Bytes("Vote_ct")) + current_stake(stake_app_id, sender)),
		
		# Checks the current vote winners total, compares to the new vote, and replaces in the case of a tie or a win
		If(App.localGet(new_vote, Bytes("Vote_ct")) >= App.localGet(App.globalGet(Bytes("Vote_leader")), Bytes("Vote_ct"))).Then(
			App.globalPut(Bytes("Vote_leader"), new_vote)
		),
		
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
    	# We default the vote leader to the current vote manager, to avoid weird situations
    	App.globalPut(Bytes("Vote_leader"), App.globalGet(Bytes("Manager"))),
		Approve(),
	)
	
	# Voting: Closing a vote
	close_vote = Seq(
		# Closes a voting sequence
		# Args:
		#	None
		close_vote_core(),
		App.globalPut(Bytes("Manager"), App.globalGet(Bytes("Vote_leader"))),
		Approve(),
	)
	
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

def manager_clear_state():
	# Cancels a user vote before clearing state to prevent exploits
	sender = Txn.sender()
	return Seq(
		If(cancel_vote_check(sender), cancel_vote_seq(sender)),
		Approve()
	)

def send_vote(client, sender, vote_recipient):
	params = client.suggested_params()
	txn = ApplicationNoOpTxn(sender['address'], params, app_id, ["Vote", vote_recipient])
	stxn = txn.sign(sender['key'])
	return send_wait_txn(client, stxn)

def create(client, sender, staking_id, init_manager=None):
	# Deploys and creates the app

	# Establishes schema
	local_ints = 4
	local_bytes = 1
	global_ints = 3
	global_bytes = 2
	global_schema = StateSchema(global_ints, global_bytes)
	local_schema = StateSchema(local_ints, local_bytes)
	
	# Compiles
	main_program, _ = compile_teal(client, manager_approval(staking_id, init_manager=Addr(init_manager)), mode=Mode.Application, version=6)
	clear_program, _ = compile_teal(client, manager_clear_state(), mode=Mode.Application, version=6)
	
	# Creates and sends the txn
	params = client.suggested_params()
	txn = ApplicationCreateTxn(sender['address'], params, no_op_on_complete(), main_program, clear_program, global_schema, local_schema)
	# stxn = txn.sign(sender['key'])
	# send_wait_txn(client, stxn)
	# app_id = client.pending_transaction_info(stxn.get_txid())["application-index"]
	
	return txn
