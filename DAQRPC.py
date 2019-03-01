#!/usr/bin/env python

#
# DAQRPC - Python wrapper for pDAQ RPC calls
#          Implemented with XML-RPC
#
# J. Jacobsen, for UW-IceCube 2006-2007
#

try:
    from DocXMLRPCServer import DocXMLRPCServer
    from xmlrpclib import ServerProxy
except ModuleNotFoundError:
    from xmlrpc.server import DocXMLRPCServer
    from xmlrpc.client import ServerProxy
import datetime
import errno
import math
import select
import socket
import sys
import threading
import time
import traceback


class RPCClient(ServerProxy):
    """Generic class for accessing methods on remote objects
    WARNING: instantiating RPCClient sets socket default timeout duration!"""

    # number of seconds before RPC call is aborted
    TIMEOUT_SECS = 120

    def __init__(self, servername, portnum, verbose=False,
                 timeout=TIMEOUT_SECS):

        self.servername = servername
        self.portnum = portnum

        hostPort = "%s:%s" % (self.servername, self.portnum)

        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # !!!!!! Warning - this is ugly !!!!!!!
        # !!!! but no other way in XMLRPC? !!!!
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        socket.setdefaulttimeout(timeout)

        ServerProxy.__init__(self, "http://" + hostPort, verbose=verbose)

    @classmethod
    def client_statistics(cls):
        return {}


class RPCServer(DocXMLRPCServer):
    "Generic class for serving methods to remote objects"
    # also inherited: register_function
    def __init__(self, portnum, servername="localhost",
                 documentation="DAQ Server", timeout=1):
        self.servername = servername
        self.portnum = portnum

        self.__running = False
        self.__timeout = timeout

        self.__stats_lock = threading.Lock()
        self.__times = {}
        self.__sock_count = 0
        self.__registered = False

        DocXMLRPCServer.__init__(self, ('', portnum),
                                                 logRequests=False)
        # note that this has to be AFTER the init above as it can be
        # set to false in the __init__
        self.allow_reuse_address = True
        self.set_server_title("Server Methods")
        self.set_server_name("DAQ server at %s:%s" % (servername, portnum))
        self.set_server_documentation(documentation)
        self.__is_shut_down = threading.Event()
        self.__running = False

    def _dispatch(self, method, params):
        if method not in self.funcs:
            raise Exception("method \"%s\" is not supported" % (method, ))

        func = self.funcs[method]

        start = time.time()
        success = False
        try:
            rtnval = func(*params)
            success = True
            return rtnval
        finally:
            with self.__stats_lock:
                if method not in self.__times:
                    self.__times[method] = RPCStats(method)
                self.__times[method].add(time.time() - start, success)

    def client_statistics(self):
        return {}

    def get_request(self):
        """Overridden in order to set so_keepalive on client
        sockets."""

        (conn, addr) = self.socket.accept()
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

        with self.__stats_lock:
            self.__sock_count += 1
            if not self.__registered:
                self.register_function(self.client_statistics)
                self.register_function(self.server_statistics)
                self.__registered = True

        return (conn, addr)

    def server_close(self):
        if self.__running:
            self.__running = False
            self.__is_shut_down.wait()
        DocXMLRPCServer.server_close(self)

    def server_statistics(self):
        # get statistics for server calls
        count = 0
        rpc_stats = {}

        # gather server statistics
        with self.__stats_lock:
            count = self.__sock_count
            for key, stats in list(self.__times.items()):
                snap = stats.snapshot()
                if snap is not None:
                    rpc_stats[key] = snap

        return {
            "socket_count": count,
            "thread_count": threading.active_count(),
            "rpc": rpc_stats,
        }

    def serve_forever(self):
        """Handle one request at a time until doomsday."""
        self.__running = True
        self.__is_shut_down.clear()
        while self.__running:
            # initialize r to an empty list - identical behaviour to a timeout
            r = []
            try:
                r, w, e = select.select([self.socket], [], [], self.__timeout)
            except select.error as err:
                if err[0] == errno.EINTR:  # Interrupted system call
                    continue
                if err[0] != errno.EBADF:  # Bad file descriptor
                    traceback.print_exc()
                break
            if r:
                self.handle_request()
        self.__is_shut_down.set()


class RPCStats(object):
    def __init__(self, method):
        self.__method = method
        self.__num = 0
        self.__min = sys.maxsize
        self.__max = -sys.maxsize - 1
        self.__sum = 0.
        self.__sumsq = 0.
        self.__succeed = 0
        self.__failed = 0

    def add(self, delta, success):
        self.__num += 1
        self.__min = min(self.__min, delta)
        self.__max = max(self.__max, delta)
        self.__sum += delta
        self.__sumsq += delta * delta
        if success:
            self.__succeed += 1
        else:
            self.__failed += 1

    def snapshot(self):
        if self.__num == 0:
            return None

        avg = self.__sum / self.__num
        x2avg = self.__sumsq / self.__num
        xavg2 = avg * avg
        try:
            rms = math.sqrt(x2avg - xavg2)
        except:
            rms = 0

        return (self.__num, self.__succeed, self.__failed, self.__min,
                self.__max, avg, rms)


if __name__ == "__main__":
    from DAQConst import DAQPort
    cl = RPCClient("localhost", DAQPort.CNCSERVER)
