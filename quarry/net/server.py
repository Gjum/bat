from twisted.internet import reactor

from quarry.net.protocol import Factory, Protocol, ProtocolError, \
    protocol_modes, register
from quarry.mojang import auth
from quarry.util import crypto


class ServerProtocol(Protocol):
    """This class represents a connection with a client"""

    uuid = None
    username = None
    username_confirmed = False

    # used to stop people breaking the login process
    # by sending packets out-of-order or duplicated
    login_expecting = 0

    def __init__(self, factory, addr):
        Protocol.__init__(self, factory, addr)
        self.server_id    = crypto.make_server_id()
        self.verify_token = crypto.make_verify_token()


    ### Convenience functions -------------------------------------------------

    def close(self, reason=None):
        # Kick the player if possible.
        if self.protocol_mode == "login":
            self.send_packet(0x00, self.buff_type.pack_json({"text": reason}))
        elif self.protocol_mode == "play":
            self.send_packet(0x40, self.buff_type.pack_json({"text": reason}))

        Protocol.close(self, reason)

    ### Callbacks -------------------------------------------------------------

    def auth_ok(self, data):
        self.username_confirmed = True
        self.uuid = data['id']

        self.player_joined()

    def player_joined(self):
        # Send login success
        self.send_packet(2,
            self.buff_type.pack_string(self.uuid) +
            self.buff_type.pack_string(self.username)
        )

        self.protocol_mode = "play"

    ### Packet handlers -------------------------------------------------------

    @register("init", 0x00)
    def packet_handshake(self, buff):
        p_protocol_version = buff.unpack_varint()
        p_server_addr = buff.unpack_string()
        p_server_port = buff.unpack("H")
        p_protocol_mode = buff.unpack_varint()

        self.protocol_mode = protocol_modes[p_protocol_mode]

        if self.factory.enforce_protocol_versions \
                and p_protocol_version not in self.factory.protocol_versions:

            self.close("Wrong protocol version")

        self.protocol_version = p_protocol_version

    @register("login", 0x00)
    def packet_login_start(self, buff):
        if self.login_expecting != 0:
            raise ProtocolError("Out-of-order login")

        self.username = buff.unpack_string()

        if self.factory.online_mode:
            self.login_expecting = 1

            # send encryption request
            self.send_packet(1,
                self.buff_type.pack_string(self.server_id) +
                self.buff_type.pack_array(self.factory.public_key) +
                self.buff_type.pack_array(self.verify_token))

        else:
            self.login_expecting = None
            self.username_confirmed = True

            # send login success
            self.send_packet(2,
                self.buff_type.pack_string("") +
                self.buff_type.pack_string(self.username))

    @register("login", 0x01)
    def packet_encryption_response(self, buff):
        if self.login_expecting != 1:
            raise ProtocolError("Out-of-order login")

        shared_secret = crypto.decrypt_secret(
            self.factory.keypair,
            buff.unpack_array())
        verify_token  = crypto.decrypt_secret(
            self.factory.keypair,
            buff.unpack_array())

        self.login_expecting = None

        if verify_token != self.verify_token:
            raise ProtocolError("Verify token incorrect")

        # enable encryption
        self.cipher.enable(shared_secret)

        # make digest
        digest = crypto.make_digest(
            self.server_id,
            shared_secret,
            self.factory.public_key)

        # do auth
        deferred = auth.has_joined(
            self.factory.auth_timeout,
            digest,
            self.username)
        deferred.addCallbacks(self.auth_ok, self.auth_failed)

    @register("status", 0x00)
    def packet_status_request(self, buff):
        d = {
            "description": {
                "text":     self.factory.motd
            },
            "players": {
                "online":   len(self.factory.players),
                "max":      self.factory.max_players
            },
            "version": {
                "name":     self.factory.protocol_versions.get(
                                self.protocol_version,
                                "???"),
                "protocol": self.protocol_version
            }
        }
        if self.factory.favicon:
            d["favicon"] = self.factory.favicon

        # send status response
        self.send_packet(0, self.buff_type.pack_json(d))

    @register("status", 0x01)
    def packet_status_ping(self, buff):
        time = buff.unpack("Q")

        # send ping
        self.send_packet(1, self.buff_type.pack("Q", time))
        self.close()


class ServerFactory(Factory):
    protocol = ServerProtocol

    motd = "A Minecraft Server"
    max_players = 20
    favicon = None
    online_mode = True
    enforce_protocol_versions = True

    protocol_versions = {
        4: "1.7.4",
        5: "1.7.10",
    }

    def __init__(self):
        self.players = []

        self.keypair = crypto.make_keypair()
        self.public_key = crypto.export_public_key(self.keypair)

    def listen(self, addr, port=25565):
        reactor.listenTCP(port, self, interface=addr)