# List of easter eggs
# If the function retuns True on the supplied name, operate on the card name here instead of the supplied one

longest_card_elemental = '''
Our Market Research Shows That
Players Like Really Long Card
Names So We Made this Card to Have
the Absolute Longest Card Name Ever
Elemental'''.strip().replace('\n', ' ')

eggs = [
    (lambda s: len(s) > 141, longest_card_elemental),
    (lambda s: not s, '______'),
]