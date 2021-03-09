#!/usr/bin/env python3.9

import os
import shutil
import asyncio
import re
import json
import requests
import io

import atoot
import scrython
import nest_asyncio
nest_asyncio.apply()

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

def get_cards(card_names):
	cards = []
	found = []
	images = []
	
	for name in card_names:
		try:
			c = scrython.cards.Named(fuzzy=name)
			found.append(c)
			cards.append(f'{c.name()} - {c.scryfall_uri()}')
		except scrython.foundation.ScryfallError:
			cards.append(f'No card named "{name}" was found.')
			
		if 1 <= len(found) <= 4:
			r = requests.get(c.image_uris(0, 'normal'), stream=True)
			
			has_pt = False
			try:
				c.power()
				has_pt = True
			except KeyError:
				pass
			
			description = c.name()
			if c.mana_cost():
				description += f' - {c.mana_cost()}'
			description += '\n' + c.type_line()
			if c.oracle_text():
				description += f'\n\n{c.oracle_text()}'
			if has_pt:
				description += f'\n\n{c.power()}/{c.toughness()}'
			
			images.append((io.BytesIO(r.content), description))
	
	return cards, images

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
			
			reply_visibility = min(('unlisted', status_visibility), key=['direct', 'private', 'unlisted', 'public'].index)
			
			media_ids = None
			
			try:
				card_names = re.findall(r'\[\[(.+?)\]\]', status_text)
			
				# ignore any statuses without cards in them
				if not card_names: continue
			
				cards, media = get_cards(card_names)
			
				reply_text = status_author
			
				if len(cards) == 1:
					reply_text += ' ' + cards[0]
				else:
					reply_text += '\n\n' + '\n'.join(cards)
			
				if media:
					media_ids = []
					for image, desc in media:
						media_ids.append((await c.upload_attachment(fileobj=image, params={}, description=desc))['id'])
			except:
				reply_text = f'{status_author} Sorry! You broke me somehow. Please let Holly know what you did!'
			
			log('Sending reply...')
			await c.create_status(status=reply_text, media_ids=media_ids, in_reply_to_id=status_id, visibility=reply_visibility)

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
