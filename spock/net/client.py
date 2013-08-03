import select
import socket
import signal
import sys
import os
import logging

from Crypto import Random

from spock.net.cflags import cflags, cevents
from spock.net.flag_handlers import fhandles
from spock.net.packet_handlers import phandles
from spock.net.event import Event
from spock.net import timer, cipher, defaults
from spock.mcp import mcdata, mcpacket
from spock import utils, smpmap, bound_buffer

rmask = select.POLLIN|select.POLLERR|select.POLLHUP
smask = select.POLLOUT|select.POLLIN|select.POLLERR|select.POLLHUP

class Client(object):
	def __init__(self, **kwargs):
		#Grab some settings
		settings = kwargs.get('settings', {})
		for setting in defaults.defstruct:
			val = kwargs.get(setting[1], settings.get(setting[1], setting[2]))
			setattr(self, setting[0], val)

		#Initialize plugin list
		#Plugins should never touch this
		self.timers = []
		self.event_handlers = {ident: [] for ident in mcdata.structs}
		self.event_handlers.update({event: [] for event in cevents})
		self.plugins = [plugin(self, self.plugin_settings.get(plugin, None)) for plugin in self.plugins]

		#Initialize socket and poll
		#Plugins should never touch these unless they know what they're doing
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.sock.setblocking(0)
		self.poll = select.poll()
		self.poll.register(self.sock, smask)

		#Initialize Event Loop/Network variables
		#Plugins should generally not touch these
		self.encrypted = False
		self.kill = False
		self.login_err = False
		self.auth_err = False
		self.rbuff = bound_buffer.BoundBuffer()
		self.sbuff = b''

		#Game State variables
		#Plugins should read these (but generally not write)
		self.world = smpmap.World()
		self.world_time = {
			'world_age': 0,
			'time_of_day': 0,
		}
		self.position = {
			'x': 0,
			'y': 0,
			'z': 0,
			'stance': 0,
			'yaw': 0,
			'pitch': 0,
			'on_ground': False,
		}
		self.health = {
			'health': 20,
			'food': 20,
			'food_saturation': 5,
		}
		self.playerlist = {}
		self.entitylist = {}
		self.spawn_position = {
			'x': 0,
			'y': 0,
			'z': 0,
		}

	#Convenience method for starting a client
	def start(self, host = 'localhost', port = 25565):
		if self.daemon: self.start_daemon()
		if (self.start_session(self.mc_username, self.mc_password)['Response'] == "Good to go!"):
			self.connect(host, port)
			self.handshake()
			self.event_loop()
		self.exit()

	def event_loop(self):
		#Set up signal handlers
		signal.signal(signal.SIGINT, self.signal_handler)
		signal.signal(signal.SIGTERM, self.signal_handler)
		#Fire off plugins that need to run after init
		self.emit('start')

		while not self.kill:
			flags = self.get_flags()
			if flags:
				for name, flag in cflags.items():
					if flags&flag:
						self.emit(name)
			for index, timer in enumerate(self.timers):
				if timer.update():
					timer.fire()
				if not timer.check():
					del self.timers[index]
			if self.daemon:
				sys.stdout.flush()
				sys.stderr.flush()

	def get_flags(self):
		self.flags = 0
		if self.sbuff:
			self.poll.register(self.sock, smask)
		else:
			self.poll.register(self.sock, rmask)
		try:
			poll = self.poll.poll(self.timeout)
		except select.error as e:
			logging.error(str(e))
			poll = []
		if poll:
			poll = poll[0][1]
			if poll&select.POLLERR: self.flags += cflags['SOCKET_ERR']
			if poll&select.POLLHUP: self.flags += cflags['SOCKET_HUP']
			if poll&select.POLLOUT: self.flags += cflags['SOCKET_SEND']
			if poll&select.POLLIN:  self.flags += cflags['SOCKET_RECV']
		if self.login_err:              self.flags += cflags['LOGIN_ERR']; self.login_err = False
		if self.auth_err:               self.flags += cflags['AUTH_ERR']; self.auth_err = False

	def emit(self, name, data=None):
		event = (data if name in mcdata.structs else Event(name, data))
		for handler in self.event_handlers[name]:
			handler(event)

	def reg_event_handler(self, events, handlers):
		if isinstance(events, str) or not hasattr(events, '__iter__'): 
			events = [events]
		if not hasattr(handlers, '__iter__'):
			handlers = [handlers]

		for event in events:
			self.event_handlers[event].extend(handlers)

	def register_timer(self, timer):
		self.timers.append(timer)

	def connect(self, host = 'localhost', port = 25565):
		if self.proxy['enabled']:
			self.host = self.proxy['host']
			self.port = self.proxy['port']
		else:
			self.host = host
			self.port = port
		try:
			print("Attempting to connect to host:", self.host, "port:", self.port)
			self.sock.connect((self.host, self.port))
		except socket.error as error:
			logging.info("Error on Connect (this is normal): " + str(error))

	def kill(self):
		self.emit('kill')
		self.kill = True

	def exit(self):
		flags = self.get_flags()
		if not flags&cflags['SOCKET_HUP']:
			self.push(mcpacket.Packet(ident = 0xFF, data = {
				'reason': 'disconnect.quitting'
				})
			)
			while self.sbuff:
				flags = self.get_flags()
				if flags&(cflags['SOCKET_ERR']|cflags['SOCKET_HUP']):
					break
				elif flags&cflags['SOCKET_SEND']:
					fhandles[cflags['SOCKET_SEND']](self)
			self.sock.close()

		if self.pidfile and os.path.exists(self.pidfile):
			os.remove(self.pidfile)

		sys.exit(0)

	def enable_crypto(self, SharedSecret):
		self.cipher = cipher.AESCipher(SharedSecret)
		self.encrypted = True

	def push(self, packet):
		bytes = packet.encode()
		self.sbuff += (self.cipher.encrypt(bytes) if self.encrypted else bytes)
		self.dispatch_packet(packet)

	def start_session(self, username, password = ''):
		self.mc_username = username
		self.mc_password = password

		#Stage 1: Login to Minecraft.net
		if self.authenticated:
			print("Attempting login with username:", username, "and password:", password)
			LoginResponse = utils.LoginToMinecraftNet(username, password)
			if (LoginResponse['Response'] == "Good to go!"):
				print(LoginResponse)
			else:
				print('Login Unsuccessful, Response:', LoginResponse['Response'])
				self.login_err = True
				if self.sess_quit:
					print("Session error, stopping...")
					self.kill = True
				return LoginResponse

			self.username = LoginResponse['Username']
			self.sessionid = LoginResponse['SessionID']
		else:
			self.username = username

		return LoginResponse

	def handshake(self):
		self.SharedSecret = Random._UserFriendlyRNG.get_random_bytes(16)

		#Stage 2: Send initial handshake
		self.push(mcpacket.Packet(ident = 0x02, data = {
			'protocol_version': mcdata.MC_PROTOCOL_VERSION,
			'username': self.username,
			'host': self.host,
			'port': self.port,
			})
		)

	def start_daemon(self, daemonize = False):
		self.daemon = True
		if daemonize:
			utils.daemonize()
			Random.atfork()

		self.pid = os.getpid()
		if self.logfile:
			sys.stdout = sys.stderr = open(self.logfile, 'w')
		if self.pidfile:
			pidf = open(self.pidfile, 'w')
			pidf.write(str(self.pid))
			pidf.close()

	def enable_proxy(self, host, port):
		self.proxy['enabled'] = True
		self.proxy['host'] = host
		self.proxy['port'] = port

	def signal_handler(self, *args):
		self.kill = True