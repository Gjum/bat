from math import floor
from spock.utils import Vec3

class Vec:
	def __init__(self, *args):
		self.set(*args)

	def __repr__(self):
		return 'Vec(%s)' % str(self.c)

	def get_dict(self):
		return {'x': self.c[0], 'y': self.c[1], 'z': self.c[2]}

	def set(self, *args):
		if len(args) == 0:
			args = [(0,0,0)]
		first_arg = args[0]
		if isinstance(first_arg, Vec):
			self.c = first_arg.c[:3]
		elif isinstance(first_arg, list) or isinstance(first_arg, tuple):
			self.c = first_arg[:3]  # argument is coords triple
		elif isinstance(first_arg, dict) \
				and 'x' in first_arg \
				and 'y' in first_arg \
				and 'z' in first_arg:
			self.c = [first_arg['x'], first_arg['y'], first_arg['z']]
		elif hasattr(first_arg, 'x') \
				and hasattr(first_arg, 'y') \
				and hasattr(first_arg, 'z'):
			self.c = [first_arg.x, first_arg.y, first_arg.z]
		elif len(args) == 3:
			self.c = args[:3]  # arguments are x, y, z
		else:
			raise ValueError('Invalid args: %s', args)
		self.c = list(map(float, self.c))
		return self

	def add(self, *args):
		d = Vec(*args)
		self.c = [c + d for c, d in zip(self.c, d.c)]
		return self

	def sub(self, *args):
		d = Vec(*args)
		self.c = [c-d for c,d in zip(self.c, d.c)]
		return self

	def round(self):
		self.c = [int(floor(c)) for c in self.c]
		return self

	def center(self):
		return self.round().add(.5, .0, .5)

	def dist_sq(self, other=None):
		v = Vec(other).sub(self) if other else self
		x, y, z = v.c
		return x*x + y*y + z*z

	def dist_cubic(self, other=None):
		v = Vec(other).sub(self) if other else self
		return sum(map(abs, v.c))

	@property
	def x(self):
		return self.c[0]

	@property
	def y(self):
		return self.c[1]

	@property
	def z(self):
		return self.c[2]

	def override_vec3(self, v3=Vec3()):
		v3.x, v3.y, v3.z = self.c
		return v3


def run_task(task, event_plugin, callback=None):
	"""
	Run the task, that is:
	- subscribe to event names that are generated by the task
	- when the event is emitted, send the event data to the generator
	:param task: generator, which generates event names
	:param event_plugin: plugin which handles all events, must provide .reg_event_handler() method
	:param callback: optional, called with task's return value when the task is finished
	:return: first generated value of the generator, or its return value if stopped immediately, or None if no generator
	"""

	listening = []

	def register(response):
		listening.clear()
		# response might be list or tuple of event names
		if isinstance(response, list) or isinstance(response, tuple):
			listening.extend(response)
		else:  # event name string or other unique value
			listening.append(response)
		# functions that otherwise return response event names
		# may return these when no event subscription is needed
		non_events = (True, False, None)
		for event in listening:
			if event in non_events:
				listening.clear()
				handler(event, {'response': event}, force=True)
				break
			else:
				event_plugin.reg_event_handler(event, handler)

	def handler(evt, data, force=False):
		if not force and evt not in listening:
			return True
		try:
			response = task.send((evt, data))
		except StopIteration as e:
			if callback:
				callback(e.value)
		else:
			register(response)
		return True  # remove this handler

	try:
		response = next(task)
	except TypeError:  # task is no generator
		return None
	except StopIteration as e:  # returned immediately
		if callback:
			callback(e.value)
		return e.value
	else:
		register(response)
	return response
