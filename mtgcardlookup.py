#!/usr/bin/env python3.9

import os # Used exactly once to check for the config file
import shutil # Used exactly once to copy the sample config file
import asyncio
import aiohttp
import re
import json
import requests
import io
import traceback
from PIL import Image

import atoot # Asynchronous Mastodon API wrapper
import scrython # Scryfall API (similar to Gatherer but I prefer Scryfall)

import nest_asyncio  # I cannot even begin to explain why I need this one.
nest_asyncio.apply() # It has something to do with Scrython using asyncio, which means I can't
                     # use it from within my asyncio code. And that's on purpose, I think.
                     # But this patches asyncio to allow that, somehow?
                     # I'm sorry, it's completely beyond me. Look it up.

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
	async def get_card_image(session, c):
		"""Return card image and description (text representation)"""

		async def download_card_image(session, c):
			async with session.get(c.image_uris(0, 'normal')) as r:
				log(f'Downloading image for {c.name()}...')

				# BytesIO stores the data in memory as a file-like object.
				# We can turn around and upload it to fedi without ever
				# touching the disk.
				b = await r.read()

				log(f'Done downloading image for {c.name()}!')

				return io.BytesIO(b)
		
		async def download_card_text(session, c):
			async with session.get(c.uri() + '?format=text') as r:
				log(f'Downloading text representation of {c.name()}...')

				text = await r.text()

				log(f'Done downloading text representation of {c.name()}!')

				return text

		try:
			front, back = map(Image.open, await asyncio.gather(
				*(get_card_image(session, face.Face(card_face)) for card_face in c.card_faces())
			))
			
			new_image = Image.new('RGB', (front.width*2, front.height))
			
			new_image.paste(front, (0, 0))
			new_image.paste(back, (front.width, 0))
			
			output = io.BytesIO()
			new_image.save(output, format=front.format)
			output.seek(0)
			
			return output
			
		except (AttributeError, KeyError):
			pass
		
		return await asyncio.gather(
			download_card_image(session, c),
			download_card_text(session, c)
		)

	# Responses list: One entry for each [[card name]] in parent, even if the
	# response is just "No card named 'CARDNAME' was found."
	responses = []
	# Cards list: Only cards that were found successfully
	cards = []

	for name in card_names:
		name = re.sub(r'<.*?>', '', name).strip()

		# Handle set codes
		if '|' in name:
			name, set_code, *_ = name.split('|')
		else:
			set_code = ''

		try:
			if len(name) > 141:
				c = scrython.cards.Named(fuzzy='Our Market Research Shows That Players Like Really Long Card Names So We Made this Card to Have the Absolute Longest Card Name Ever Elemental')
			elif len(name) == 0:
				c = scrython.cards.Named(fuzzy='_____')
			else:
				c = scrython.cards.Named(fuzzy=name, set=set_code)
			cards.append(c)
			responses.append(f'{c.name()} - {c.scryfall_uri()}')
		except scrython.foundation.ScryfallError:
			if set_code:
				responses.append(f'No card named "{name}" from set with code {set_code.upper()} was found.')
			else:
				responses.append(f'No card named "{name}" was found.')

	# Download card images.
	# A status can only have four images on it, so we can't necessarily include
	# every card mentioned in the status.
	# The reason I choose to include /no/ images in that case is that someone
	# linking to more than 4 cards is probably talking about enough different things
	# that it would be weird for the first four they happened to mention to have images.
	# Like if someone's posting a decklist it would be weird for the first four cards to
	# be treated as special like that.
	if 1 <= len(cards) <= 4:
		async with aiohttp.ClientSession() as session:
			images = await asyncio.gather(
				*(get_card_image(session, c) for c in cards)
			)
	else:
		images = None

	return responses, images

async def update_followers(c, me):
	log('Updating followed accounts...')
	accounts_following_me = set(map(lambda a: a['id'], await c.get_all(c.account_followers(me))))
	accounts_i_follow = set(map(lambda a: a['id'], await c.get_all(c.account_following(me))))

	# Accounts that follow me that I don't follow
	to_follow = accounts_following_me - accounts_i_follow

	# Accounts I follow that don't follow me
	to_unfollow = accounts_i_follow - accounts_following_me

	if to_follow:
		# Note that the bot listens for follows and tries to follow
		# back instantly. This is /usually/ dead code but it's a failsafe
		# in case someone followed while the bot was down or something.
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

async def handle_status(c, status):
	# Ignore all reblogs
	if status.get('reblog'): return

	status_id = status['id']
	status_author = '@' + status['account']['acct']
	status_text = status['content']
	status_visibility = status['visibility']
	
	# Reply unlisted or at the same visibility as the parent, whichever is
	# more restrictive
	# I realized after writing this that I don't /think/ it ever matters?
	# I think replies behave the same on public and unlisted. But I'm not 100%
	# sure so it stays.
	reply_visibility = min(('unlisted', status_visibility), key=['direct', 'private', 'unlisted', 'public'].index)

	media_ids = None

	try:
		card_names = re.findall(r'\[\[(.*?)\]\]', status_text)

		# ignore any statuses without cards in them
		if not card_names: return

		cards, media = await get_cards(card_names)

		reply_text = status_author

		# Just a personal preference thing. If I ask for one card, put the
		# text on the same line as the mention. If I ask for more, start the
		# list a couple of lines down.
		if len(cards) == 1:
			reply_text += ' ' + cards[0]
		else:
			reply_text += '\n\n' + '\n'.join(cards)

		if media:
			try:
				media_ids = []
				for image, desc in media:
					media_ids.append((await c.upload_attachment(fileobj=image, params={}, description=desc))['id'])
			except atoot.api.RatelimitError:
				media_ids = None
				reply_text += '\n\nMedia attachments are temporarily disabled due to API restrictions, they will return shortly.'
	except Exception as e:
		# Oops!
		log(traceback.print_exc(), Severity.ERROR)
		reply_text = f'{status_author} Sorry! You broke me somehow. Please let Holly know what you did!'

	log('Sending reply...')
	try:
		reply = await c.create_status(status=reply_text, media_ids=media_ids, in_reply_to_id=status_id, visibility=reply_visibility)
		log(f'Reply sent! {reply["uri"]}')
	except atoot.api.UnprocessedError as e:
		log(f'Could not send reply!', Severity.ERROR)
		log(traceback.format_exc(), Severity.ERROR)
		error_msg = 'An error occured sending the reply. This most likely means that it would have been greater than 500 characters. If it was something else, please let Holly know!'
		await c.create_status(status=f'{status_author} {error_msg}', in_reply_to_id=status_id, visibility=reply_visibility)

async def handle_follow(c, follow):
	id = follow['account']['id']
	log(f'Received follow from {id}, following back')
	await c.account_follow(id)

async def listen(c, me):
	log('Listening...')
	async with c.streaming('user') as stream:
		async for msg in stream:
			event = msg.json()['event']
			payload = json.loads(msg.json()['payload'])

			# We only care about these two events
			if event == 'update':
				mentions_me = any((mentioned['id'] == me['id'] for mentioned in payload['mentions']))

				# Ignore any incoming status that mentions us
				# We're also going to get a ntification event, we'll handle it there
				if not mentions_me:
					await handle_status(c, payload)
			elif event == 'notification':
				if payload['type'] == 'follow':
					await handle_follow(c, payload)
				elif payload['type'] == 'mention':
					await handle_status(c, payload['status'])

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
