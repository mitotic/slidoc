#!/usr/bin/env python
#

"""
multiproxy: Simple HTTP Relaying Reverse-Proxy using Tornado
 - Transfer-Encoding is not implemented for inbound data
"""

import datetime
import errno
import functools
import hashlib
import hmac
import logging
import os
import random
import socket
import struct
import sys
import time

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

try:
    import ssl
except ImportError:
    ssl = None

from tornado import httpserver
from tornado import ioloop
from tornado import iostream
from tornado import netutil
from tornado import stack_context
from tornado import web
from tornado import websocket

MAX_SCAN_HEADER_BUFFER = 4096                         # For partial header parsing (Host: ...)
MAX_FULL_HEADER_BUFFER = 10 * MAX_SCAN_HEADER_BUFFER  # For full header parsing

READ_CHUNK_SIZE = 4096                                # For relaying
MAX_BUFFER_SIZE = 100 * READ_CHUNK_SIZE               # For tornado

MAX_CONNECTIONS = 10000
MIN_KEEPALIVE_TIME = 5 * 60

PERIODIC_SEC = 10                                    # Interval for periodic cleanup callback
RETRY_SEC = 5

# Bandwidth limits
ENFORCE_PER_IP_LIMITS = False                        # Set to enforce bandwidth limits per IP address
LIMIT_PERIOD   = 25 * 3600                           # Period over which limits/blocks are reset
LIMIT_REQUESTS  = 30000                              # Number of requests allowed over period
LIMIT_BYTES     = 1000 * 1000000                     # Limit over period per IP address
LIMIT_REQ_BYTES =   10 * 1000000                     # Limit per request

# Request stats
ITIME         = 0
IREQUESTS     = 1
IBYTES        = 2
ILOGGED_REQS  = 3
ILOGGED_BYTES = 4
ILOGGED_TIME  = 5

LOGNAME = "multiproxy"

Multiplex_websocket = True

def get_value(header_dict, header_name, default=None, strip_value=""):
    """ Return last header value, or default value (None)
    If strip_value, remove strip_value (e.g., 'keep-alive') if it occurs in addition to other values
    """
    if header_name in header_dict:
        value = header_dict[header_name][-1]
        if value and strip_value:
            new_value = ", ".join(x.strip() for x in value.split(",") if x.strip().lower() != strip_value.lower())
            return new_value or value
        else:
            return value
    else:
        return default

get_random_hmac_key = "hmac_key"
def get_random60(hex=False, integer=False):
    """Return "60-bit" randomness as 10 Base64URL characters (default) or 15 hex digits (or as an integer)
   Uses HMAC for safer randomness (using MD5 for speed)
    """
    randstr = struct.pack("Q", random.randint(0, (1 << 60)-1) )
    hmac_obj = hmac.new(str(get_random_hmac_key), randstr, digestmod=hashlib.md5)
    if integer:
        return struct.unpack("Q", hmac_obj.digest()[:8])[0]   # 64 bits of the MD5 HMAC
    elif hex:
        return hmac_obj.hexdigest()[:15]                   # 60 bits of the MD5 HMAC
    else:
        return b64url_encode(hmac_obj.digest()[:9])[:10]   # 60 bits of the MD5 HMAC 

def make_unix_server_socket(socket_path):
    try:
        # Delete any previous socket
        os.unlink(socket_path)
    except OSError:
        if os.path.exists(socket_path):
            raise

    sock = netutil.bind_unix_socket(socket_path)
    os.chmod(socket_path, 0700)
    return sock

def create_unix_client_socket(socket_path):
    if not os.path.exists(socket_path):
        raise Exception('Unix socket path %s does not exist' % socket_path)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)
    return sock
    
class StatusException(Exception):
    """ Exception for sending error messages to HTTP client
    """
    pass

class ShutdownException(Exception):
    """ Quiet shutdown
    """
    pass

class RedirectException(Exception):
    """ Exception for redirecting HTTP client
    """
    pass

class PermanentRedirectException(RedirectException):
    """ Exception for permanently redirecting HTTP client
    """
    pass

class ChunkyStream(object):
    """ Extends IOStream to also read a chunk of data, rather than just delimited data
        or a fixed number of bytes.
        Unconsumed/buffered input data continues to be processed even after stream is closed.
    """
    _CHUNKY_MAX_RESET_COUNT = 1
    def __init__(self, *args, **kwargs):
        """ kwarg chunk_timeout can be used to close idle connections
        """
        self._chunky_timeout = kwargs.pop("chunk_timeout", None)
        super(ChunkyStream, self).__init__(*args, **kwargs)

        self._read_chunk = None
        self._chunky_prev_consumed = 0
        self._chunky_reset_count = 0

        self._chunky_close_callback = None
        self._chunky_close_immediate = False

        self._chunky_close_reported = False
        self._chunky_close_finalized = False
        super(ChunkyStream, self).set_close_callback(self._chunky_close)

        self._chunky_active = True
        if self._chunky_timeout:
            self._chunky_timeout_cb = self.io_loop.add_timeout(time.time()+self._chunky_timeout, self._chunky_timeout_check)
        else:
            self._chunky_timeout_cb = None


    def set_close_callback(self, callback, immediate=False):
        """Call the given callback when the stream is closed.
        If immediate, close immediately without processing any buffered data.
        (The normal behaviour is to close after processing buffered data.)
        """
        self._chunky_close_callback = callback
        self._chunky_close_immediate = immediate

    def _chunky_close(self):
        if self._chunky_close_finalized:
            return

        self._chunky_close_finalized = True
        if self._chunky_timeout_cb:
            try:
                self.io_loop.remove_timeout(self._chunky_timeout_cb)
            except Exception:
                pass
            self._chunky_timeout_cb = None

        if self._chunky_close_callback:
            callback = self._chunky_close_callback
            self._chunky_close_callback = None
            callback()

    def _chunky_timeout_check(self):
        self._chunky_timeout_cb = None
        if not self._chunky_active and not self._read_buffer_size:
            self.close()
        else:
            self._chunky_active = False
            self._chunky_timeout_cb = self.io_loop.add_timeout(time.time()+self._chunky_timeout, self._chunky_timeout_check)

    def _consume(self, loc):
        self._chunky_active = True
        data = super(ChunkyStream, self)._consume(loc)
        self._chunky_prev_consumed = len(data)
        return data

    def unconsume(self, data, reset=False):
        """ Unconsume data, usually after reading a chunk. Normally you can only unconsume
        fewer bytes than were read in the last consume operation. To unconsume more,
        use the reset option.
        """
        self._chunky_active = True
        if reset:
            if self._chunky_reset_count >= self._CHUNKY_MAX_RESET_COUNT:
                # This check prevents inadvertent looping when using consume
                raise Exception("Too many resets for ChunkyStream")
            self._chunky_reset_count += 1
            self._chunky_prev_consumed = 0
        else:
            if len(data) >= self._chunky_prev_consumed:
                raise Exception("Must unconsume less data than was previously consumed (unless resetting)")
            self._chunky_prev_consumed -= len(data)

        self._read_buffer.appendleft(data)
        self._read_buffer_size += len(data)

    def data_available(self):
        return bool(self._read_buffer_size)

    def read_chunk(self, callback):
        """Call callback when we have read a chunk of data.
        Callback may return a null string, when stream is closed.
        """
        assert not self._read_callback, "Already reading"
        self._chunky_active = True
        return self.read_bytes(READ_CHUNK_SIZE, callback=callback, partial=True)

class ChunkyIOStream(ChunkyStream, iostream.IOStream):
    pass

class ChunkySSLIOStream(ChunkyStream, iostream.SSLIOStream):
    pass

class ProxyServer(object):
    """ HTTP Proxy Server:
        Stream refers to the wrapped 2-way TCP connection. There is an external stream
        (browser<->proxy) and an internal stream (proxy<->server).
        Pipeline refers to the two-way information transfer between the external browser and
        the internal server, by combining the external and internal streams.
        Flow refers to one way information transfer (external->internal or internal->external)
    """
    def __init__(self, host, port, handler_class, proxy_id="", io_loop=None, xheaders=False,
                 multiplex_params=(), relay_keep_alive=True, local_handler_class=None, masquerade="", host_header=None,
                 application=None, block_addrs=[], block_filename=None, weblog_file=None, log_interval=60,
                 ssl_options={}, idle_timeout=None, debug=False):
        """ Listens for TCP requests.
        If the unique proxy_id string is omitted, "host:port" is used as proxy_id.
        If io_loop is not specified, a new io_loop is created and started (blocking)
        If xheaders, create and forward X-Real-Ip and X-Scheme upstream.
        If multiplex_params=(class, websock_offset), multiplex websocket connections using class
        If relay_keep_alive, keep internal relay connection alive as long as external is alive (DEFAULT: True)
        If local_handler_class, URLs matching compiled regexp local_handler_class.PATH_RE are "handed over" for local processing (no transforms will be applied)
        If masquerade, overwrite outbound Server: header
        If host_header, overwrite inbound Host: header
        If block_addrs, block all IP addresses in list of addresses or subnets (/24, /16, /8 only)
        log_interval (in sec) for writing to log file (per IP address)
        idle_timeout to timeout idle external connections
        """
        self.host = host
        self.ports = {"http": port}
        self.handler_class = handler_class
        self.proxy_id = proxy_id or "%s:%s" % (host, port)
        if not io_loop:
            self.io_loop = ioloop.IOLoop.current()
        else:
            self.io_loop = io_loop

        self.xheaders = xheaders
        self.multiplex_params = multiplex_params
        self.relay_keep_alive = relay_keep_alive
        self.local_handler_class = local_handler_class
        self.masquerade = masquerade
        self.host_header = host_header
        self.application = application

        self.block_filename = block_filename
        self.weblog_file = weblog_file
        self.log_interval = log_interval
        self.ssl_options = ssl_options
        self.idle_timeout = idle_timeout
        self.debug = debug

        self.protocol = "https" if self.ssl_options else "http"

        self.perm_block_addrs = set()
        self.perm_block_subnets = set()
        self.temp_block_addrs = OrderedDict()
        self.request_stats = OrderedDict()           # ip_addr: [time, requests, bytes]
        self.connections = OrderedDict()             # (ip_addr, ip_port): handler (Ordered by last response time)

        self.max_connection_count = None
        self.min_keepalive_time = None
        self.stopped = False

        self.socks = {}
        for server_type, port in self.ports.iteritems():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setblocking(0)
            sock.bind((self.host, port))
            if self.ssl_options:
                sock = ssl.wrap_socket(sock, server_side=True,
                                       **self.ssl_options)
            sock.listen(128)
            self.io_loop.add_handler(sock.fileno(),
                                     functools.partial(self.connection_ready, server_type),
                                     self.io_loop.READ)
            self.socks[server_type] = sock
            logging.warning("%s: Listening for %s on %s:%d", LOGNAME, server_type, self.host, port)

        self.periodic_loop = ioloop.PeriodicCallback(self.periodic_callback, PERIODIC_SEC*1000,
                                                     io_loop=self.io_loop)
        self.last_period_time = time.time()
        self.periodic_loop.start()

        # Update blocked list, creating files if need be
        if block_addrs:
            for addr in block_addrs:
                self.block(addr)
        self.update_blocked_list()

        if not io_loop:
            self.io_loop.start()

    def stop(self):
        if self.stopped:
            return

        self.stopped = True
        for server_type, sock in self.socks.iteritems():
            try:
                self.io_loop.remove_handler(sock.fileno())
            except Exception:
                pass
            sock.close()

    def periodic_callback(self):
        cur_time = time.time()
        self.last_period_time = cur_time

        refresh_time = cur_time - LIMIT_PERIOD
        for addr in self.temp_block_addrs.keys():
            # Delete expired temporary block entries
            if self.temp_block_addrs[addr] < refresh_time:
                del self.temp_block_addrs[addr]
            else:
                break

        for addr in self.request_stats.keys():
            # Delete expired stats entries
            if self.request_stats[addr][ITIME] < refresh_time:
                del self.request_stats[addr]
            else:
                break

        if self.weblog_file:
            self.weblog_file.flush()

    def connection_ready(self, server_type, fd, events):
        while True:
            try:
                connection, address = self.socks[server_type].accept()
            except socket.error, e:
                if e.args[0] not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise
                return
            connection.setblocking(0)

            if self.isblocked(address[0]):
                try:
                    ##connection.write("HTTP/1.1 509 Bandwidth Limit Exceeded\r\n\r\n")
                    connection.close()
                except Exception:
                    pass
                return

            if self.ssl_options:
                stream_class = ChunkySSLIOStream
            else:
                stream_class = ChunkyIOStream

            external_stream = stream_class(connection, io_loop=self.io_loop,
                                           chunk_timeout=self.idle_timeout,
                                           read_chunk_size=READ_CHUNK_SIZE,
                                           max_buffer_size=MAX_BUFFER_SIZE)

            # Initiate connect handler
            pipeline = Pipeline(server_type, external_stream, address, self)
            pipeline.start()

    def isblocked(self, ip_addr):
        comps = ip_addr.split(".")
        subnets = [comps[0], ".".join(comps[:2]), ".".join(comps[:3])]
        subnet_match = any(subnet in self.perm_block_subnets for subnet in subnets)
        return subnet_match or ip_addr in self.perm_block_addrs or ip_addr in self.temp_block_addrs

    def temp_block(self, ip_addr, msg):
        self.temp_block_addrs[ip_addr] = time.time()
        logging.error("%s: Temporarily blocked %s: %s", LOGNAME, ip_addr, msg)
        self.update_blocked_list()

    def block(self, ip_addr):
        self.perm_block_addrs.add(ip_addr)
        self.perm_block_subnets.add(self.subnet_prefix(ip_addr))
        logging.error("%s: Permanently blocked %s", LOGNAME, ip_addr)
        self.update_blocked_list()


    def unblock(self, ip_addr):
        self.perm_block_addrs.discard(ip_addr)
        self.perm_block_subnets.discard(self.subnet_prefix(ip_addr))
        if ip_addr in self.temp_block_addrs:
            del self.temp_block_addrs[ip_addr]
        logging.error("%s: Unblocked %s", LOGNAME, ip_addr)
        self.update_blocked_list()

    def update_blocked_list(self):
        if not self.block_filename:
            return
        try:
            with open(self.block_filename, "w") as f:
                for addr in self.perm_block_addrs:
                    f.write(addr+"\n")
                for addr in self.temp_block_addrs:
                    f.write(addr+"\n")
        except Exception, excp:
            logging.error("%s: Error in writing to blocked addr file %s: %s", LOGNAME, self.block_filename, excp)

    def subnet_prefix(self, ip_subnet):
        """ Returns subnet prefix associated with /8, /16, /24 subnet
        """
        if "/" not in ip_subnet:
            return ip_subnet

        # Handle subnet (/8, /16, /24 only)
        netaddr, sep, subnet = ip_subnet.partition("/")
        comps = netaddr.split(".")
        if subnet == "8":
            return comps(0)
        elif subnet == "16":
            return ".".join(comps[:2])
        elif subnet == "24":
            return ".".join(comps[:3])
        else:
            # Incorrect fallback
            return netaddr
                

class Pipeline(object):
    """ Two-way information pipeline created by splicing external and internal streams.
    """
    METHODS = {"http": ("GET", "HEAD", "POST", "PUT")}

    def __init__(self, server_type, external_stream, from_address, proxy_server):
        self.server_type = server_type
        self.external_stream = external_stream
        self.from_address = from_address
        self.ip_addr, self.ip_port = from_address
        self.proxy_server = proxy_server

        self.xheaders = proxy_server.xheaders
        self.multiplex_params = proxy_server.multiplex_params
        self.relay_keep_alive = proxy_server.relay_keep_alive
        self.local_handler_class = proxy_server.local_handler_class
        self.debug = proxy_server.debug

        self.allowed_methods = Pipeline.METHODS[self.server_type]
        self.last_request = 0

        self.internal_sock = None
        self.internal_stream = None
        self.opened = False
        self.closed = False
        self.internal_closed = False
        self.requests = []

        self.cur_req = None
        self.cur_resp = None

        self.request_protocol = "HTTP/1.1"
        self.host_spec = None
        self.relay_address = None

        self.inbound_flow = None
        self.outbound_flow = None
        self.inbound_connect_state = None
        self.reconnect = False
        self.closing_internal_only = False
        self.err_response = None

        self.refresh_connection_entry(new=True) # May shutdown, if overloaded

        self.external_stream.set_close_callback(functools.partial(self.shutdown, external=True), immediate=True)
        self.inbound_flow = FlowHandler(self, external_stream, inbound=True)

    def start(self):
        self.inbound_flow.start_flow()

    def send_err_response(self, err_response, wrap=False):
        """ Write error response and then shutdown pipeline.
        """
        assert len(self.requests) == 1
        assert isinstance(err_response, str)

        if wrap:
            err_response = self.request_protocol+" "+err_response+"\r\n\r\n"

        self.err_response = err_response
        try:
            self.external_stream.write(err_response, self.shutdown)
        except Exception:
            self.shutdown()
        return

    def shutdown(self, internal=False, external=False, block_msg="", quiet=False):
        """ Set internal to True if shutdown is triggered by close of internal connection
            Set external to True if shutdown is triggered by close of external connection
            If block_msg is set, the IP address is blocked, and an error message is logged.
        """
        if internal and self.closing_internal_only:
            # Reconnecting; ignore internal close
            return

        if self.closed:
            return
        self.closed = True

        self.refresh_connection_entry(delete=True)

        if block_msg:
            # Temporarily block IP address
            self.proxy_server.temp_block(self.ip_addr, block_msg)

        if not internal:
            # Shutdown internal connection
            try:
                self.internal_stream.close()
            except Exception:
                pass

        if not external:
            if quiet:
                self.shutdown_external()
            else:
                try:
                    if not self.opened and not self.err_response:
                        # Internal stream was never opened; return error status, then shutdown
                        self.external_stream.write(self.request_protocol+" 502 Bad Gateway (internal never opened)\r\n\r\n", self.shutdown_external)
                    else:
                        # Close external stream after flushing data
                        self.external_stream.write("", self.shutdown_external)
                except Exception:
                    self.shutdown_external()

    def shutdown_external(self):
        """Shutdown external connection
        """
        try:
            self.external_stream.close()
        except Exception:
            pass

    def allow_bandwidth(self, data_len=None, inbound=False):
        """ If limits are exceeded, shutdown pipeline immediately and return False
        (Client will only see blocked message on next connect attempt)
        """

        if not ENFORCE_PER_IP_LIMITS:
            return True

        if self.ip_addr not in self.proxy_server.request_stats:
            # Start collecting request stats for this address
            self.proxy_server.request_stats[self.ip_addr] = [time.time(), 0, 0, 0, 0, 0] # [time, requests, bytes, logged_reqs, logged_bytes]
            
        stats = self.proxy_server.request_stats[self.ip_addr]
        if data_len is None:
            # New request
            stats[IREQUESTS] += 1
            if stats[IREQUESTS] <= LIMIT_REQUESTS:
                return True
        else:
            # Count bytes
            stats[IBYTES] += data_len
            if stats[IBYTES] <= LIMIT_BYTES:
                if inbound:
                    self.cur_req.request_bytes += data_len
                    if self.cur_req.request_bytes <= LIMIT_REQ_BYTES:
                        return True
                else:
                    self.cur_resp.response_bytes += data_len
                    return True

        # Limit exceeded
        req_bytes = self.cur_req.request_bytes if self.cur_req else 0
        init_time = datetime.datetime.utcfromtimestamp(stats[ITIME]).replace(microsecond=0).isoformat()+"Z"
        self.shutdown(block_msg="start=%s, reqs=%d, bytes=%d, req_bytes=%d" % (init_time, stats[IREQUESTS], stats[IBYTES], req_bytes))
        return False

    def refresh_connection_entry(self, new=False, delete=False):
        self.last_refresh_time = self.proxy_server.last_period_time
        if self.from_address in self.proxy_server.connections:
            # Clear any old entry
            del self.proxy_server.connections[self.from_address]

        if new:
            if len(self.proxy_server.connections) >= MAX_CONNECTIONS:
                # Connection overload
                if self.ip_addr not in self.proxy_server.request_stats:
                    # Drop connections from new IP addresses
                    self.send_err_response("503 Service Unavailable", wrap=True)
                    return

                keepalive_time = None
                while len(self.proxy_server.connections) >= MAX_CONNECTIONS:
                    # Drop the most stale connections
                    address, handler = self.proxy_server.connections.popitem(last=False)
                    keepalive_time = self.last_refresh_time - handler.last_refresh_time
                    if keepalive_time < MIN_KEEPALIVE_TIME:
                        # Allow connection limit to be exceeded to guarantee min keepalive time
                        logging.error("%s: Exceeding connection limit: %s", LOGNAME, len(self.proxy_server.connections))
                        break
                    try:
                        handler.shutdown()
                    except Exception:
                        pass

                if keepalive_time is not None:
                    if self.proxy_server.min_keepalive_time is None or self.proxy_server.min_keepalive_time > keepalive_time:
                        self.proxy_server.min_keepalive_time = keepalive_time

            if self.proxy_server.max_connection_count is None or self.proxy_server.max_connection_count < len(self.proxy_server.connections):
                self.proxy_server.max_connection_count = len(self.proxy_server.connections)


        if not delete:
            # Add new entry
            self.proxy_server.connections[self.from_address] = self

    def log_request(self, request_handler):
        stats = self.proxy_server.request_stats.get(self.ip_addr)
        if stats:
            # Update stats
            cur_time = time.time()
            if cur_time - stats[ILOGGED_TIME] < self.proxy_server.log_interval:
                return
            stats[ILOGGED_TIME] = cur_time
            stats[ILOGGED_BYTES] = stats[IBYTES]
            stats[ILOGGED_REQS] = stats[IREQUESTS]

        log_str = str(request_handler)
        if self.proxy_server.weblog_file:
            self.proxy_server.weblog_file.write(log_str)

    def reconnect_internal(self):
        self.reconnect = False
        self.close_internal_only()
        self.connect_to_internal()

    def close_internal_only(self):
        self.outbound_flow = None
        self.inbound_flow.set_write_stream(None)
        self.internal_stream.set_close_callback(None)
        self.closing_internal_only = True
        try:
            # self.closing_internal_only must be set to True here to prevent pipeline shutdown
            # due to internal stream being closed (not needed anymore?)
            self.internal_stream.close()
        except Exception:
            pass
        finally:
            self.closing_internal_only = False

        self.internal_stream = None
        self.opened = False

    def connect_to_internal(self):
        if self.closed:
            return

        try:
            assert self.relay_address, "Relay address not defined for internal connection"
            if isinstance(self.relay_address, tuple):
                # relay_address = (host, addr)
                socket_type = socket.AF_INET
            else:
                # relay_address = unix_domain_socket_addr
                socket_type = socket.AF_UNIX
            self.internal_sock = socket.socket(socket_type, socket.SOCK_STREAM, 0)
            self.internal_stream = ChunkyIOStream(self.internal_sock, io_loop=self.proxy_server.io_loop)
            self.internal_stream.set_close_callback(self.internal_disconnected)
            self.internal_stream.connect(self.relay_address, self.internal_connected)
        except Exception, excp:
            logging.warning("multiproxy: Internal connect error: %s", excp)
            self.inbound_flow.error_response("502 Bad Gateway (internal connect error)")

    def internal_disconnected(self):
        self.internal_closed = True

    def internal_connected(self):
        if self.closed:
            return

        self.internal_closed = False
        self.opened = True

        self.outbound_flow = FlowHandler(self, self.internal_stream, self.external_stream,
                                         inbound=False)

        self.outbound_flow.start_flow()

        self.inbound_flow.set_write_stream(self.internal_stream)
        self.inbound_flow.relay_headers()


class RequestHandler(object):
    """ Handles single request in the pipelined HTTP connection
    """
    def __init__(self, request_index, ip_addr, protocol):
        self.request_index = request_index
        self.ip_addr = ip_addr
        self.protocol = protocol

        self.status = ""
        self.err_response = ""
        self.call_hook = None

        self.req_headers = {}
        self.resp_headers = {}

        self.request_method = None
        self.orig_request_uri = None
        self.request_uri = None
        self.request_protocol = "HTTP/1.1"
        self.resp_protocol = None
        self.orig_status = None

        self.content_length = None

        self.req_upgrade_header = None
        self.resp_upgrade_header = None

        self.req_connection_header = None
        self.resp_connection_header = None

        self.req_content_length = None
        self.resp_content_length = None

        self.request_bytes = 0
        self.response_bytes = 0

    def __str__(self):
        log_str = '%s - - [%s] "%s %s %s" %s %s %s %s\n' % (self.ip_addr,
                     time.strftime("%d/%b/%Y:%H:%M:%S %z", time.gmtime()),
                     self.request_method, self.request_uri or "-", self.request_protocol,
                     self.status.split()[0] if self.status else "0",
                     self.resp_content_length or 0,
                     get_value(self.req_headers, "referer","-"),
                     get_value(self.req_headers, "user-agent", "-") or "-")
        return log_str

    def get_relay_addr_uri(self, pipeline, header_list):
        """ Returns relay (host, port) or socket (e.g., unix domain socket from socketpair)
        May modify self.request_uri or header list (excluding the first element)
        Raises exception if connection not allowed.
        """
        raise StatusException("403 Forbidden (relay unimplemented)")

    def check_request(self, request_line):
        """ Checks request (after request line has been parsed, but before headers)
        Returns (modified_request_line, handover_type)
        """
        return (request_line, "")

    def check_response(self, status, pipeline, header_list):
        """ Checks response (after response headers have been parsed)
        May modify header list (excluding the first element)
        Returns None or raises exception if connection is to be aborted
        """
        pass

    def parse_headers(self, header_list, replace={}, drop=[]):
        """ Returns tuple of modified header list and OrderedDict with lower-case header
        names as keys and a list of one or more header values for each key.
        replace: {lower_case_name, value}
        drop: list of lower_case header names to be dropped
        Content-Length value are converted to integers in the dict
        """
        mod_header_list = []
        header_dict = OrderedDict()
        last_header_values = None
        for header in header_list:
            if header[0] in (" ", "\t"):
                # Continuation header; append to last header
                if not last_header_values:
                    last_header_values[-1] += header
                    mod_header_list.append(header)
                continue

            header_name_raw, sep, header_value = header.partition(":")
            header_name = header_name_raw.lower()
            header_value = header_value.lstrip()

            if drop and header_name in drop:
                last_header_values = None
                continue

            if replace and header_name in replace:
                header = header_name_raw+": "+replace[header_name]

            mod_header_list.append(header)

            if header_name not in header_dict:
                header_dict[header_name] = []

            if header_name == "content-length":
                try:
                    header_value = int(header_value.strip())
                    if header_value < 0:
                        header_value = None
                except Exception:
                    header_value = None
                
            last_header_values = header_dict[header_name]
            last_header_values.append(header_value)

        return mod_header_list, header_dict

    def process_request_line(self, pipeline, request_line):
        """ Parses request line
        Returns (modified_request_line, handover_type)
        """
        request_line = request_line.lstrip()

        tem_method, sep, tem_tail = request_line.partition(" ")
        self.orig_request_uri, sep, tem_protocol = tem_tail.lstrip().partition(" ")

        request_line, handover = self.check_request(request_line)

        self.request_method, sep, request_tail = request_line.partition(" ")
        self.request_uri, sep, self.request_protocol = request_tail.lstrip().partition(" ")
        self.request_protocol = self.request_protocol.strip().upper()

        pipeline.request_protocol = self.request_protocol

        return (request_line, handover)

    def process_inbound_headers(self, pipeline, headers):
        """ Parses headers (after request line) to check if connection should be allowed.
        Returns (modified/unmodified headers, handover_type)
        Raises exception if connection is not allowed, or redirected, or upgrading
        """
        ##print >> sys.stderr, "DEBUG process_inbound_headers", pipeline.ip_port, headers[0], "\n", headers[-1]
        handover = ""
        if pipeline.local_handler_class and pipeline.local_handler_class.PATH_RE.match(self.request_uri):
            return (headers, "localhandler")

        new_headers = headers[0:1]

        replace = {}
        if pipeline.proxy_server.host_header:
            replace["host"] = pipeline.proxy_server.host_header
        drop = ["x-real-ip", "x-scheme"] if pipeline.xheaders else []
            
        mod_headers, header_dict = self.parse_headers(headers[1:], drop=drop, replace=replace)

        new_headers += mod_headers
        # Proxy headers
        if pipeline.xheaders:
            new_headers += ["X-Real-Ip: %s" % pipeline.ip_addr]
            new_headers += ["X-Scheme: %s" % self.protocol]

        self.req_headers = header_dict

        self.req_upgrade_header = get_value(header_dict, "upgrade", "").lower()

        if "connection" in header_dict:
            self.req_connection_header = get_value(header_dict, "connection", strip_value="keep-alive").lower()
            pipeline.inbound_connect_state = self.req_connection_header
            if pipeline.multiplex_params and self.req_connection_header == "upgrade":
                if self.req_upgrade_header == "websocket" and Multiplex_websocket:
                    handover = self.req_upgrade_header

        if "content-length" in header_dict:
            values = header_dict["content-length"]
            if len(values) != 1 or values[0] is None:
                # Only one content-length value is allowed
                raise StatusException("400 Bad Request (multiple content length)")
            self.req_content_length = values[0]
            pipeline.inbound_flow.content_length = self.req_content_length 

        # Raise exceptions after parsing headers (for better logging)
        if not self.orig_request_uri.startswith("/"):
            raise StatusException("400 Bad request")

        if self.request_method not in pipeline.allowed_methods:
            raise StatusException("405 Method Not Allowed")

        if "transfer-encoding" in header_dict:
            raise StatusException("501 Not Implemented (transfer-encoding)")

        if self.request_protocol == "HTTP/1.0":
            host_spec = ""
        ##  raise StatusException("505 HTTP Version Not Supported")
        else:
            host_spec = get_value(header_dict, "host", "").strip().lower()

        if pipeline.host_spec:
            if host_spec != pipeline.host_spec:
                # Host mismatch in pipelined request
                raise StatusException("400 Bad Request (host mismatch)")
        else:
            # Initialize host spec
            pipeline.host_spec = host_spec

        # Determine relay address etc. (may raise exception)
        relay_addr = self.get_relay_addr_uri(pipeline, new_headers)
        if pipeline.relay_address and pipeline.relay_address != relay_addr:
            # Relay address has changed; reconnect
            pipeline.reconnect = True
            logging.debug("%s: Reconnecting to %s", LOGNAME, relay_addr)

        pipeline.relay_address = relay_addr

        if self.request_uri != self.orig_request_uri:
            # Modified request URI
            new_headers[0] = "%s %s %s" % (self.request_method, self.request_uri, self.request_protocol)

        if self.request_method not in ("POST", "PUT"):
            pipeline.inbound_flow.content_length = 0

        elif self.req_content_length is None:
            raise StatusException("411 Length Required")

        ##print >> sys.stderr, "DEBUG process_inbound_headers2", pipeline.ip_port, pipeline.inbound_flow.passthru, self.req_content_length, self.req_upgrade_header, get_value(header_dict, "upgrade", ""), "'"+get_value(header_dict, "connection", "NONE2", strip_value="keep-alive")+"'", handover or "NONE3"

        return (new_headers, handover)

    def process_response_line(self, pipeline, response_line):
        """ Parses response line
        Returns (modified_response_line, handover_type)
        """
        response_line = response_line.lstrip()

        self.resp_protocol, sep, self.orig_status = response_line.partition(" ")
        self.orig_status = self.orig_status.lstrip()

        return (response_line, "")

    def process_outbound_headers(self, pipeline, headers):
        """
        Returns (modified/unmodified headers, handover_type)
        Raises exception if connection is not allowed or redirected.
        """
        assert self.request_method
        if self.resp_protocol != self.request_protocol:
            raise StatusException("500 Internal Server Error (mismatched HTTP version)")

        new_headers = headers[0:1]

        replace = {}
        if pipeline.proxy_server.masquerade:
            replace["server"] = pipeline.proxy_server.masquerade
            
        mod_headers, header_dict = self.parse_headers(headers[1:], replace=replace)

        new_headers += mod_headers
        self.resp_headers = header_dict

        self.resp_upgrade_header = get_value(header_dict, "upgrade", "").lower()

        if "connection" in header_dict:
            self.resp_connection_header = get_value(header_dict,"connection", strip_value="keep-alive").lower()

        if "content-length" in header_dict:
            values = header_dict["content-length"]
            if len(values) != 1 or values[0] is None:
                # Only one content-length value is allowed
                raise StatusException("500 Internal Server Error (multiple content length)")
            self.resp_content_length = values[0]
            pipeline.outbound_flow.content_length = self.resp_content_length

        if "transfer-encoding" in header_dict:
            raise StatusException("500 Internal Server Error (transfer-encoding not supported)")

        # May raise exception
        self.check_response(self.orig_status, pipeline, new_headers)

        if self.request_method == "GET" and self.req_upgrade_header == "websocket" and self.req_connection_header == "upgrade":
            if self.orig_status.startswith("101 ") and self.resp_upgrade_header == "websocket" and self.resp_connection_header == "upgrade":
                # Websocket upgrade succeeded
                pipeline.inbound_flow.passthru = True
                pipeline.outbound_flow.passthru = True

                # Resume reading inbound data
                pipeline.inbound_flow.data_sent()
            else:
                # Websocket upgrade failed; close connection
                self.resp_connection_header = "close"

        elif self.resp_content_length is None:
            if self.resp_connection_header == "close":
                pipeline.outbound_flow.passthru = True
            else:
                pipeline.outbound_flow.content_length = 0

        ##print >> sys.stderr, "DEBUG process_outbound_headers2", pipeline.ip_port, pipeline.outbound_flow.passthru, self.resp_content_length

        # Update status only after successful header processing (for better error handling)
        self.status = self.orig_status

        if pipeline.outbound_flow.passthru:
            # Request "completed"; log it
            pipeline.log_request(self)

        return (new_headers, "")


class FlowHandler(object):
    """ Handles one-way (inbound or outbound) data flow (sequence of headers+content)
        between browser and server, relayed by the proxy.
    """
    def __init__(self, pipeline, read_stream, write_stream=None, inbound=False):
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.pipeline = pipeline
        self.inbound = inbound

        self.header_buffer = []
        self.header_incomplete = ""

        self.passthru = False       # If true, relay all data (no further header parsing etc.)
        self.flow_closed = False
        self.proxy_connection_id = None

    def set_write_stream(self, write_stream):
        self.write_stream = write_stream

    def reset_content(self):
        self.content_bytes = 0
        self.content_length = None

    def handover_connection(self, handover):
        # Handover connection
        ##print >> sys.stderr, "DEBUG handover_connection", handover, self.pipeline.host_spec, self.pipeline.relay_address
        external_stream = self.read_stream

        # Shutdown pipeline; pretend it is an external shutdown
        self.pipeline.shutdown(external=True)

        if handover == "localhandler":
            http_connection = httpserver.HTTPConnection(external_stream,
                                                        self.pipeline.from_address,
                                                        self.local_request_callback,
                                                        xheaders=self.pipeline.xheaders)
            return

        assert isinstance(self.pipeline.relay_address, tuple)
        host, port = self.pipeline.relay_address
        port += self.pipeline.multiplex_params[1]
        self.proxy_connection_id = self.pipeline.proxy_server.proxy_id + "," + ("%s:%s" % (host, port))

        # Setup connection
        conn = self.pipeline.multiplex_params[0].get_client(self.proxy_connection_id,
                                                        connect=(host, port))
        if handover == "websocket":
            http_connection = httpserver.HTTPConnection(external_stream,
                                                        self.pipeline.from_address,
                                                        self.ws_request_callback,
                                                        xheaders=self.pipeline.xheaders)


    def ws_request_callback(self, request):
        ##print >> sys.stderr, "DEBUG ws_request_callback", request
        ws_request_handler = ProxyWebSocket(self.pipeline.proxy_server.application, request,
                                            connection_id=self.proxy_connection_id,
                                            multiplex_class=self.pipeline.multiplex_params[0])
        ws_request_handler._execute([])

    def local_request_callback(self, request):
        ##print >> sys.stderr, "DEBUG local_request_callback", request
        local_request_handler = self.pipeline.local_handler_class(self.pipeline.proxy_server.application,
                                                                  request,
                                                                  proxy_id=self.pipeline.proxy_server.proxy_id)
        local_request_handler._execute([])

    def error_response(self, status="403 Forbidden", err_headers=[], err_body="", terminal=False):
        """ Set error response in appropriate request handler.
        If internal stream is not open, or if terminal, error response is sent immediately, followed by
        shutdown.
        """
        if not self.pipeline.requests or (len(self.pipeline.requests) == 1 and self.pipeline.requests[0].status):
            # Immediate shutdown (because response status has already been transmitted)
            self.pipeline.shutdown()
            return

        request_handler = self.pipeline.cur_req if self.inbound else self.pipeline.cur_resp
        if not request_handler or request_handler.status:
            self.pipeline.shutdown()
            return

        send_now = terminal or not self.pipeline.opened or (len(self.pipeline.requests) == 1 and self.pipeline.requests[0] is request_handler)

        request_handler.status = status
        header_str = "\r\n".join(err_headers)+"\r\n" if err_headers else ""

        request_handler.err_response = request_handler.request_protocol+" "+status+"\r\n"+header_str+"\r\n"+err_body

        if send_now:
            # Log request, send error response and then shutdown
            self.pipeline.log_request(request_handler)
            self.pipeline.send_err_response(request_handler.err_response)

    def recv_headers(self, data):
        """ Receives header portion of data stream
        """
        ##print >> sys.stderr, "DEBUG recv_headers inbound=", self.inbound, len(data), self.pipeline.requests, self.pipeline.cur_req, self.pipeline.cur_resp, data[:80]
        if self.pipeline.closed:
            return

        if self.flow_closed:
            return

        if not data:
            # Stream closed
            if self.inbound:
                self.pipeline.shutdown(external=True)
            else:
                self.pipeline.shutdown(internal=True)
            return

        # Request handler
        new_headers = False
        if self.inbound:
            if not self.pipeline.cur_req:
                self.pipeline.last_request += 1

                # Instantiate RequestHandler
                self.pipeline.cur_req = self.pipeline.proxy_server.handler_class(self.pipeline.last_request,
                                                       self.pipeline.ip_addr,
                                                       self.pipeline.proxy_server.protocol)
                self.pipeline.requests.append(self.pipeline.cur_req)
                new_headers = True
            
            request_handler = self.pipeline.cur_req
        else:
            assert self.pipeline.requests
            if not self.pipeline.cur_resp:
                self.pipeline.cur_resp = self.pipeline.requests[0]
                new_headers = True
                assert not self.pipeline.cur_resp.response_bytes
            request_handler = self.pipeline.cur_resp

        if new_headers:
            # New request/response headers
            self.header_buffer = []
            self.header_incomplete = ""
            if self.inbound:
                if not self.pipeline.allow_bandwidth(data_len=None, inbound=self.inbound):
                    return

        if not self.header_buffer:
            # Look for request/response line
            assert data
            if self.header_incomplete.endswith("\r"):
                if not data.startswith("\n"):
                    self.error_response("400 Bad Request", terminal=True)
                    return
                # First line complete
                data = data[1:]
                self.header_buffer.append(self.header_incomplete[:-1])
                self.header_incomplete = ""
            else:
                req_part, sep, remaining = data.partition("\r\n")
                if sep:
                    # First line complete
                    self.header_buffer.append(self.header_incomplete+req_part)
                    self.header_incomplete = ""
                    data = remaining
                else:
                    # Incomplete first line (consume all data)
                    self.header_incomplete += data
                    data = ""

            if self.header_buffer:
                # First line (request/response) has been parsed
                if not self.header_buffer[0]:
                    self.error_response("400 Bad Request", terminal=True)
                    return
                try:
                    if self.inbound:
                        # Error exceptions should be raised after reading all headers, for
                        # cleaner handling of consumed data.
                        mod_line, handover = request_handler.process_request_line(self.pipeline, self.header_buffer[0])
                    else:
                        mod_line, handover = request_handler.process_response_line(self.pipeline, self.header_buffer[0])
                    self.header_buffer[0] = mod_line

                except Exception, excp:
                    # Unknown exception
                    if self.pipeline.debug:
                        logging.warning("%s: Error - %s", LOGNAME, excp, exc_info=True)
                    self.error_response("500 Internal Server Error", terminal=True)
                    return

                if handover:
                    req_data = self.header_buffer[0] + "\r\n" + data
                    self.read_stream.unconsume(req_data, reset=True)
                    self.handover_connection(handover)
                    return

        unconsumed = ""
        headers_complete = False
        if not self.header_buffer:
            assert not data
        elif data:
            # Parse data after first line
            if self.header_incomplete.endswith("\r") and data.startswith("\n"):
                # Previous text ended with CR and new text starts with LF;
                # Prepend the CR byte to data (at least two bytes will be consumed later)
                data = self.header_incomplete[-1] + data
                self.header_incomplete = self.header_incomplete[:-1]

            # The following should consume at least two bytes of data
            if not self.header_incomplete and data.startswith("\r\n"):
                # Previous text ended with CR-LF ("null" incomplete header) and new text starts with CR-LF
                # Consume two bytes and unconsume the rest
                headers_complete = True
                unconsumed = data[2:]
                data = ""
            else:
                # Either previous text did not end with CR-LF or new text does not start with CR-LF
                j = data.find("\r\n\r\n")
                if j >= 0:
                    # Headers complete; consume 4 or more bytes and unconsume remaining data
                    headers_complete = True
                    unconsumed = data[j+4:]
                    add_headers = data[:j].split("\r\n")   # If j==0, this would yield [""], which is OK
                    data = ""
                    add_headers[0] = self.header_incomplete + add_headers[0]
                    assert add_headers[0] and add_headers[-1]
                    self.header_buffer += add_headers
                    self.header_incomplete = ""
                else:
                    # Incomplete; consume all data
                    add_headers = data.split("\r\n")
                    data = ""
                    add_headers[0] = self.header_incomplete + add_headers[0]
                    assert add_headers[0]
                    self.header_buffer += add_headers[:-1]
                    self.header_incomplete = add_headers[-1]   # May be a "null" header

        header_len = sum(len(header)+2 for header in self.header_buffer) + len(self.header_incomplete)

        if not headers_complete:
            if  header_len >= MAX_FULL_HEADER_BUFFER:
                status = "413 Request Entity Too Large"
                if self.pipeline.debug:
                    logging.warning("%s: Status %s - %s", LOGNAME, request_handler.request_method, status)
                self.error_response(status, terminal=True)
                return
                
            try:
                # Read some more data
                self.read_stream.read_chunk(self.recv_headers)
                return
            except Exception, excp:
                if not isinstance(excp, IOError):
                    logging.warning("multiproxy: read_chunk ERROR: %s", excp)
                self.pipeline.shutdown()
                return

        # Process complete headers after unconsuming extra data
        self.read_stream.unconsume(unconsumed)

        try:
            # Process headers, and perhaps modify them
            if self.inbound:
                mod_headers, handover = request_handler.process_inbound_headers(self.pipeline, self.header_buffer)
            else:
                mod_headers, handover = request_handler.process_outbound_headers(self.pipeline, self.header_buffer)

            self.header_buffer = mod_headers

        except RedirectException, excp:
            # Partition exception description to remove any appended trace info
            redirect_url, sep, tail = excp.args[0].partition("\n")
            status_str = "301 Moved Permanently" if isinstance(excp, PermanentRedirectException) else "302 Found"
            err_headers = ["Location: " + redirect_url]
            self.error_response(status_str, err_headers=err_headers)
            return

        except StatusException, excp:
            # Partition exception description to remove any appended trace info
            status, sep, tail = excp.args[0].partition("\n")
            self.error_response(status)
            return

        except ShutdownException, excp:
            # Quiet shutdown
            self.pipeline.shutdown(quiet=True)
            return

        except Exception, excp:
            # Unknown exception
            if self.pipeline.debug:
                logging.warning("%s: Error - %s", LOGNAME, excp, exc_info=True)
            self.error_response("500 Internal Server Error", terminal=True)
            return

        finally:
            pass

        # Count header bytes
        if not self.pipeline.allow_bandwidth(header_len, inbound=self.inbound):
            return

        if handover:
            if self.inbound and callable(handover):
                request_handler.call_hook = handover
            else:
                # Unconsume modified headers
                header_str = self.get_complete_header_str()
                self.read_stream.unconsume(header_str, reset=True)
                self.handover_connection(handover)
                return

        assert self.pipeline.requests
        if not self.write_stream:
            # Make first internal connection
            self.pipeline.connect_to_internal()

        elif self.pipeline.reconnect:
            if len(self.pipeline.requests) == 1:
                # Only current request in pipeline; reconnect now
                self.pipeline.reconnect_internal()
            else:
                # Reconnect when response queue is cleared
                pass
        elif request_handler.call_hook:
            # Do not relay request headers (or content)
            assert not self.content_length
            self.data_sent()
        else:
            # Relay headers
            self.relay_headers()

    def get_complete_header_str(self):
        return "\r\n".join(self.header_buffer) + "\r\n\r\n"

    def relay_headers(self):
        # Relay headers
        header_str = self.get_complete_header_str()
        self.header_buffer = []
        self.recv_data(header_str, headers=True)

    def recv_data(self, data, headers=False):
        """ Receives data (headers or content), relays it, and waits for next chunk
        """
        if self.pipeline.closed:
            return

        ##print >> sys.stderr, "DEBUG recv_data", self.inbound, len(data)
        if not data:
            # Stream closed
            if self.inbound:
                self.pipeline.shutdown(external=True)
            else:
                self.pipeline.shutdown(internal=True)
            return

        if not headers:
            if not self.passthru:
                unconsumed_count = (self.content_bytes + len(data)) - self.content_length
                if unconsumed_count > 0:
                    assert unconsumed_count < len(data)
                    self.read_stream.unconsume(data[-unconsumed_count:])
                    data = data[:-unconsumed_count]

                # Must process some content; if all content was processed previously,
                # internal_sent would have initiated processing of next request
                assert data

                self.content_bytes += len(data)

            # Note: header bytes have already been counted
            if not self.pipeline.allow_bandwidth(len(data), inbound=self.inbound):
                return

        # Relay data
        try:
            if self.inbound:
                # For inbound data, wait until data has been relayed
                self.write_stream.write(data, callback=self.data_sent)
            else:
                # For outbound data, do not wait until data has been relayed
                # (waiting causes IO errors in the upstream socket, for some reason!)
                self.write_stream.write(data)
                self.data_sent()
        except Exception:
            self.pipeline.shutdown()
            return

    def start_flow(self):
        self.reset_content()
        self.content_length = 0
        self.data_sent(start=True)

    def data_sent(self, start=False):
        if self.pipeline.closed:
            return

        ##print >> sys.stderr, "DEBUG data_sent", self.pipeline.ip_port, "inbound=", self.inbound, self.content_bytes, self.content_length, self.passthru, self.pipeline.internal_closed

        if self.passthru or self.content_bytes < self.content_length:
            # Relay content; read more content data for request/response
            callback = self.recv_data
        else:
            # Content relay complete for request
            assert self.content_bytes == self.content_length

            self.reset_content()
            callback = self.recv_headers
            if self.inbound:
                if self.pipeline.inbound_connect_state in ("close", "upgrade"):
                    # Do not read any more inbound data
                    # (When upgrade handshake is complete, more passthru data will be read)
                    return

                self.pipeline.cur_req = None
                # Wait to read inbound header data for new request

            else: # Outbound response completed
                if not start:
                    assert self.pipeline.requests
                    completed_request = self.pipeline.requests.pop(0)
                    assert self.pipeline.cur_resp is completed_request
                    assert completed_request.status

                    self.pipeline.log_request(completed_request)
                    ##print >> sys.stderr, "DEBUG completed_request*********", completed_request, self.pipeline.requests, completed_request.request_uri, completed_request.status

                    if completed_request.resp_connection_header == "close" or completed_request.request_protocol == "HTTP/1.0":
                        self.pipeline.shutdown()
                        return

                self.pipeline.cur_resp = None

                if len(self.pipeline.requests) == 1 and self.pipeline.reconnect:
                    # Reconnect to different internal host (will close this outbound flow)
                    self.pipeline.reconnect_internal()
                    return

                if self.pipeline.requests:
                    # One or more requests remain to be processed
                    if self.pipeline.requests[0].err_response:
                        # Error response for next request; transmit and shutdown pipeline
                        self.pipeline.send_err_response(self.pipeline.requests[0].err_response)
                        return

                    if self.pipeline.requests[0].call_hook:
                        # Call internal hook (e.g., static file server) to respond to request
                        # TODO: Implement WSGI interface for call_hook
                        self.pipeline.cur_resp = self.pipeline.requests[0]
                        try:
                            status, hook_data = self.pipeline.cur_resp.call_hook(self.pipeline.cur_resp)
                            self.pipeline.cur_resp.status = status
                        except Exception, excp:
                            if self.pipeline.debug:
                                logging.warning("%s: Call hook error - %s", LOGNAME, excp, exc_info=True)
                            self.pipeline.send_err_response("500 Internal Server Error", wrap=True)
                            return

                        # For outbound data, do not wait until data has been relayed
                        # (waiting causes IO errors in the upstream socket, for some reason!)
                        # Should perhaps be: self.write_stream.write(hook_data, callback=self.data_sent)
                        self.write_stream.write(hook_data)
                        self.pipeline.proxy_server.io_loop.add_callback(self.data_sent)
                        return

                elif not self.pipeline.relay_keep_alive and not self.read_stream.data_available():
                    # No requests left in pipeline; close internal connection
                    # recv_header will re-open internal connection later
                    self.pipeline.close_internal_only()
                    return
                # Wait to read outbound header data for remaining (or new) relayed requests

        if not self.inbound and self.pipeline.internal_closed and not self.read_stream.data_available():
            self.pipeline.shutdown()
            return

        try:
            self.read_stream.read_chunk(callback)
        except Exception, excp:
            if not isinstance(excp, IOError):
                logging.warning("multiproxy: read_chunk ERROR: %s", excp)
            self.pipeline.shutdown()

if __name__ == "__main__":
    Site_prefixes = {'': 8081, 'alpha': 8081, 'beta': 8082}
    class TestRequestHandler(RequestHandler):
        def get_relay_addr_uri(self, pipeline, header_list):
            """ Returns relay host, port.
            May modify self.request_uri or header list (excluding the first element)
            Raises exception if connection not allowed.
            """
            print >> sys.stderr, 'relay: request_uri=', self.request_uri
            comps = self.request_uri.split('/')
            if len(comps) > 1 and comps[1] and comps[1] in Site_prefixes:
                self.request_uri = self.request_uri[1+len(comps[1]):]
                if not self.request_uri:
                    self.request_uri = '/'
                return ("localhost", Site_prefixes[comps[1]])
            elif '' in Site_prefixes:
                return ("localhost", Site_prefixes[''])
            else:
                raise Exception('Invalid path '+self.request_uri)

    HOST, PORT = "localhost", 8801
    IO_loop = ioloop.IOLoop.instance()
    Proxy_server = ProxyServer(HOST, PORT, TestRequestHandler, io_loop=IO_loop, log_interval=0,
                               xheaders=True, masquerade="server/1.2345", debug=True)

    IO_loop.start()
