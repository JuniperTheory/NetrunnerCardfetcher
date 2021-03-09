#!/usr/bin/env python3.9

import os
import shutil
import asyncio
import re
import json
import requests
import io
import sys
import traceback

import atoot
import scrython
import nest_asyncio
nest_asyncio.apply()

import face

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

async def get_cards(card_names):
	async def download_card_image(session, c):
		log(f'Downloading image for {c.name()}...')
		url = c.image_uris(0, 'normal')
		async with session.get(url) as r:
			image = io.BytesIO(await r.read())

		log(f'Done downloading image for {c.name()}!')
		return image

	def get_text_representation(c):
		try:
			# Double face cards have to be treated ENTIRELY DIFFERENTLY
			# Instead of card objects we just get a list of two dictionaries.
			# I've decided to try to reuse at much code as possible by jerryrigging
			# my own Face object that can be passed into my card parsing logic
			return '\n\n//\n\n'.join((
				get_text_representation(face.Face(card_face)) for card_face in c.card_faces()
			))
		except:
			pass

		# I genuinely think this is the best way to check whether a card has
		# power/toughness, considering how Scrython is implemented.
		# Can't even check for Creature type because of stuff like Vehicles.
		try:
			c.power()
			has_pt = True
		except KeyError:
			has_pt = False

		ret = c.name() # All cards have a name.

		# Some cards (lands, [[Wheel of Fate]], whatever) don't have mana costs.
		# Add it if it's there.
		if c.mana_cost():
			ret += f' - {c.mana_cost()}'

		# All cards have a type line.
		ret += '\n' + c.type_line()

		# Funnily enough, not all cards have oracle text.
		# It feels like they should, but that's ignoring vanilla creatures.
		if c.oracle_text():
			ret += f'\n\n{c.oracle_text()}'

		# Finally, power/toughness.
		if has_pt:
			ret += f'\n\n{c.power()}/{c.toughness()}'

		return ret

	cards = []
	found = []

	for name in card_names:
		try:
			c = scrython.cards.Named(fuzzy=name)
			found.append(c)
			cards.append(f'{c.name()} - {c.scryfall_uri()}')
		except scrython.foundation.ScryfallError:
			cards.append(f'No card named "{name}" was found.')

	if 1 <= len(found) <= 4:
		# download card images
		async with aiohttp.ClientSession() as session:
			images = list(zip(await asyncio.gather(
					*(download_card_image(session, c) for c in found)
			), (get_text_representation(c) for c in found)))

	else:
		images = None

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

				status_id = status['id']
				status_author = '@' + status['account']['acct']
				status_text = status['content']
				status_visibility = status['visibility']
			except:
				try:
					if status['type'] == 'follow':
						id = status['account']['id']
						log(f'Received follow from {id}, following back')
						await c.account_follow(id)
				except:
					log('Event came in that we don\'t know how to handle.', Severity.WARNING)
					log(status, Severity.WARNING)

				continue

			reply_visibility = min(('unlisted', status_visibility), key=['direct', 'private', 'unlisted', 'public'].index)

			media_ids = None

			try:
				card_names = re.findall(r'\[\[(.+?)\]\]', status_text)

				# ignore any statuses without cards in them
				if not card_names: continue

				cards, media = await get_cards(card_names)

				reply_text = status_author

				if len(cards) == 1:
					reply_text += ' ' + cards[0]
				else:
					reply_text += '\n\n' + '\n'.join(cards)

				if media:
					media_ids = []
					for image, desc in media:
						media_ids.append((await c.upload_attachment(fileobj=image, params={}, description=desc))['id'])
			except Exception as e:
				log(traceback.print_exc(), Severity.ERROR)
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
