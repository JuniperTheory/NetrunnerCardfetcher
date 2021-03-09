from enum import Enum
from datetime import datetime

DEBUG = True

class Severity(Enum):
	MESSAGE = 'M'
	WARNING = 'W'
	ERROR = 'E'

def log(message, severity=Severity.MESSAGE):
	if DEBUG:
		print(f'{datetime.now()}: [{severity.value}] {message}')
