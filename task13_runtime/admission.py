"""Private named-pipe capability, not a model tool or HTTP server."""
from multiprocessing.connection import Client
from task13_runtime.common import HostError

class Admission:
    def __init__(self, capability):
        self.capability = capability

    def call(self, operation, **arguments):
        with Client(self.capability['address'], family='AF_PIPE',
                    authkey=bytes.fromhex(self.capability['auth'])) as connection:
            connection.send({'session':self.capability['session'], 'operation':operation, 'arguments':arguments})
            reply = connection.recv()
        if 'error' in reply:
            raise HostError(reply['error']['code'], reply['error']['message'])
        return reply['result']

    def reserve(self, byte_count, turn_id, max_tokens=4096, request_sha256=None):
        return self.call('reserve', byte_count=byte_count, turn_id=turn_id,
                         max_tokens=max_tokens, request_sha256=request_sha256)

    def settle(self, attempt_id, usage=None, error=None):
        return self.call('settle', attempt_id=attempt_id, usage=usage, error=error)

    def stop(self, reason):
        return self.call('fatal', reason=reason)
