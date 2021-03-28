# Double face cards have to be treated ENTIRELY DIFFERENTLY
# Instead of card objects we just get a list of two dictionaries.
# I've decided to try to reuse at much code as possible by jerryrigging
# my own Face object that can be passed into my card parsing logic

# The only reason this class is here is as a "fake" Card class. It
# implements just enough of the Card interface for python's duck typing
# to let it through for my purposes.

# I wouldn't have to do any of this if Scrython wasn't so needlessly bizarre.
class Face:
	def __init__(self, d):
		self.d = d

	def name(self):
		return self.d['name']

	def mana_cost(self):
		return self.d['mana_cost']

	def type_line(self):
		return self.d['type_line']

	def oracle_text(self):
		return self.d['oracle_text']

	def power(self):
		return self.d['power']

	def toughness(self):
		return self.d['toughness']

	def image_uris(self, _, layout):
		return self.d['image_uris'][layout]