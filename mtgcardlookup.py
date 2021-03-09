import os
import shutil
import asyncio
import re
import json

import atoot

from debug import *

async def startup():
	log('Starting up...')
	if not os.path.exists('config.py'):
		log('Config file not found, copying', Severity.WARNING)
		shutil.copyfile('config.sample.py', 'config.py')
	
	import config
	async with atoot.client(config.instance, access_token=config.access_token) as c:
		log('Connected to server!')
		me = await c.verify_account_credentials()
		log('Credentials verified!')
		
		tasks = []
		
		tasks.append(asyncio.create_task(listen(c, me)))
		tasks.append(asyncio.create_task(repeat(5 * 60, update_followers, c, me)))
		
		for t in tasks:
			await t

async def update_followers(c, me):
	log('Updating followed accounts...')
	accounts_following_me = set(map(lambda a: a['id'], await c.account_followers(me)))
	accounts_i_follow = set(map(lambda a: a['id'], await c.account_following(me)))
	
	# accounts that follow me that i don't follow
	to_follow = accounts_following_me - accounts_i_follow
	
	# accounts i follow that don't follow me
	to_unfollow = accounts_i_follow - accounts_following_me
	
	if to_follow:
		log(f'{len(to_follow)} accounts to follow:')
		for account in to_follow:
			await c.account_follow(account)
			log(f'Followed {account}')
	else:
		log('No accounts to follow.')
	
	if to_unfollow:
		log(f'{len(to_unfollow)} accounts to unfollow:')
		for account in to_unfollow:
			await c.account_unfollow(account)
			log(f'Unfollowed {account}')
	else:
		log('No accounts to unfollow.')

async def listen(c, me):
	log('Listening...')
	async with c.streaming('user') as stream:
		async for msg in stream:
			status = json.loads(msg.json()['payload'])
			
			try:
				# two events come in for the statuses, one of them has the status nested deeper
				# just ignore that one
				if 'status' in status: continue
			except:
				# ignore any events we don't know how to handle
				continue
			
			status_id = status['id']
			status_author = '@' + status['account']['acct']
			status_text = status['content']
			status_visibility = status['visibility']
			
			cards = re.findall(r'\[\[(.+?)\]\]', status_text)
			
			# ignore any statuses without cards in them
			if not cards: continue
			
			reply_text = status_author + ' ' + ', '.join(cards)
			reply_visibility = min(('unlisted', status_visibility), key=['direct', 'private', 'unlisted', 'public'].index)
			
			log('Sending reply...')
			await c.create_status(status=reply_text, in_reply_to_id=status_id, visibility=reply_visibility)

# https://stackoverflow.com/a/55505152/2114129
async def repeat(interval, func, *args, **kwargs):
    """Run func every interval seconds.

    If func has not finished before *interval*, will run again
    immediately when the previous iteration finished.

    *args and **kwargs are passed as the arguments to func.
    """
    while True:
        await asyncio.gather(
            func(*args, **kwargs),
            asyncio.sleep(interval),
        )

if __name__ == '__main__':
	asyncio.run(startup())