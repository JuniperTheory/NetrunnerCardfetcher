# Double face cards have to be treated ENTIRELY DIFFERENTLY
# Instead of card objects we just get a list of two dictionaries.
# I've decided to try to reuse at much code as possible by jerryrigging
# my own Face object that can be passed into my card parsing logic
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