'''
Voting utility methods
'''

from utils import global_must_get, increment_global, local_must_get, send_wait_txn
from pyteal import Subroutine, TealType, Expr, Bytes, App, Seq, Assert, And, \
	Global, Int, Not, Txn
from algosdk.future.transaction import ApplicationNoOpTxn

# TODO: Go through and double check application array for including proper apps

@Subroutine(TealType.uint64)
def current_stake(stake_app_id, address) -> Expr:
	# Helper method to get the current stake for an address
	return local_must_get(Bytes("Stake"), stake_app_id, address)

# TODO: Cleanup imports at end
	
@Subroutine(TealType.uint64)
def has_voted(address, app_id) -> Expr:
	# Checks if `address` has voted in the last vote in `app_id`
	
	current_vote_id = global_must_get(Bytes("Vote_id"), app_id)
	last_voted_id = App.localGetEx(address, app_id, Bytes("Vote_id"))
	
	 # We don't check hasValue because a user may *never* have voted in this
	 #	vote, so a 0 value check is sufficient
	return Seq(last_voted_id, current_vote_id == last_voted_id.value())
	
@Subroutine(TealType.uint64)
def is_resolved(app_id):
	# Checks if voting is resolved in `app_id`
	return global_must_get(Bytes("Resolved"), app_id)

'''
Internal methods
	These methods can be used within a voting contract
'''

@Subroutine(TealType.uint64)
def is_voting_allowed() -> Expr:
	# Checks if voting is allowed
	return App.globalGet(Bytes("Vote_end")) > Global.latest_timestamp()

@Subroutine(TealType.uint64)
def cancel_vote_check(address) -> Expr:
	# Checks if a vote can be cancelled
	return And(
		is_voting_allowed(),
		has_voted(address, App.id()),
	)
	
'''
Core functionality and utility methods
'''

'''
init_vote
	Initializing a vote should look similar to the following
	init_vote = Seq(
		init_vote_core(vote_interval, vote_length),	
		
		ZERO_OUT_VOTES_IF_NEEDED(),	
		
		Approve(),
	)
'''

def init_vote_core(vote_interval, vote_length):
	# Runs the core portions of initializing a vote: does basic checks and sets proper variables
	return Seq(
		Assert(
			And(
				is_resolved(App.id()), # Previous vote must be resolved
				App.globalGet(Bytes("Vote_end")) + vote_interval <= Global.latest_timestamp() # The time since the last vote end must be at least the min_interval
			)
		),
		increment_global(Bytes("Vote_id"), Int(1)),
		App.globalPut(Bytes("Resolved"), Int(0)),
		App.globalPut(Bytes("Vote_end"), Global.latest_timestamp() + vote_length),
	)
	
'''
close_vote
	Closing a vote should look similar to  the following
	close_vote = Seq(
		close_vote_core(),
		
		FIND_WINNER(),
		
		Approve(),
	)
'''

def close_vote_core():
	# Rybs the core portions of close_cote
	return Seq(
		Assert(
			And(
				Not(is_resolved(App.id())),
				Not(is_voting_allowed())
			)
		),
		App.globalPut(Bytes("Resolved"), Int(1)),
	)
	
'''
send_vote
	Sending a vote should look similar to the following
	send_vote = Seq(
		send_vote_core(VALID_VOTE_CHECK, NEW_VOTE),
		
		TALLY_VOTE(),
		
		Approve(),
	)
'''

def send_vote_core(valid_vote_check, new_vote, stake_app_id):
	sender = Txn.sender()
	return Seq(
		Assert(
			And(
				valid_vote_check(new_vote),
				is_voting_allowed(),
				Not(has_voted(sender, App.id())),
			)
		),
		App.localPut(sender, Bytes("Vote_id"), App.globalGet(Bytes("Vote_id"))),
		App.localPut(sender, Bytes("Choice"), new_vote),
		# We track votes to protect against a weird edge case
		App.localPut(sender, Bytes("Used_votes"), current_stake(stake_app_id, sender)),
	)

# Calling functionality
#	Future improvements may include:
#		- Adding ability to do these in a group transaction

# send_vote must be implemented in each vote instance

def cancel_vote(client, sender, app_id):
	params = client.suggested_params()
	txn = ApplicationNoOpTxn(sender['pk'], params, app_id, ["Cancel"])
	stxn = txn.sign(sender['sk'])
	return send_wait_txn(client, stxn)

def init_vote(client, sender, app_id):
	params = client.suggested_params()
	txn = ApplicationNoOpTxn(sender['pk'], params, app_id, ["Init"])
	stxn = txn.sign(sender['sk'])
	return send_wait_txn(client, stxn)

def close_vote(client, sender, app_id):
	params = client.suggested_params()
	txn = ApplicationNoOpTxn(sender['pk'], params, app_id, ["Close"])
	stxn = txn.sign(sender['sk'])
	return send_wait_txn(client, stxn)
