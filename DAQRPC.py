#!/usr/bin/env python

#
# DAQRPC - Python wrapper for pDAQ RPC calls
#          Implemented with XML-RPC
#
# J. Jacobsen, for UW-IceCube 2006-2007
#

import DocXMLRPCServer
import datetime
import math
import select
import socket
import traceback
import xmlrpclib
import threading


class RPCClient(xmlrpclib.ServerProxy):
    """Generic class for accessing methods on remote objects
    WARNING: instantiating RPCClient sets socket default timeout duration!"""

    # number of seconds before RPC call is aborted
    TIMEOUT_SECS = 120

    def __init__(self, servername, portnum, verbose=0, timeout=TIMEOUT_SECS):

        self.servername = servername
        self.portnum = portnum
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # !!!!!! Warning - this is ugly !!!!!!!
        # !!!! but no other way in XMLRPC? !!!!
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        socket.setdefaulttimeout(timeout)
        xmlrpclib.ServerProxy.__init__(self,
                                       "http://%s:%s" %
                                       (self.servername, self.portnum),
                                       verbose=verbose)
        self.statDict = {}

    def showStats(self):
        "Return string representation of accumulated statistics"
        if self.nCalls() == 0:
            return "None"

        results_list = ["%25s: %s" % (x, self.statDict[x].report()) for x in self.callList()]
        return "\n".join(results_list)

    def nCalls(self):
        "Return number of invocations of RPC method"
        return len(self.statDict)

    def callList(self):
        "Return list of registered methods"
        return self.statDict.keys()

    def rpccall(self, method, *rest):
        "Wrapper to benchmark speed of various RPC calls"
        if not method in self.statDict:
            self.statDict[method] = RPCStat()
        tstart = datetime.datetime.now()

        result = None
        try:
            m = getattr(self, method)
            result = m(*rest)
        except AttributeError:
            raise NameError("method: '%s' does not exist" % method)
        finally:
            self.statDict[method].tally(datetime.datetime.now() - tstart)

        return result


class RPCServer(DocXMLRPCServer.DocXMLRPCServer):
    "Generic class for serving methods to remote objects"
    # also inherited: register_function
    def __init__(self, portnum, servername="localhost",
                 documentation="DAQ Server", timeout=1):
        self.servername = servername
        self.portnum = portnum

        self.__running = False
        self.__timeout = timeout

        DocXMLRPCServer.DocXMLRPCServer.__init__(self, ('', portnum),
                                                 logRequests=False)
        # note that this has to be AFTER the init above as it can be
        # set to false in the __init__
        self.allow_reuse_address = True
        self.set_server_title("Server Methods")
        self.set_server_name("DAQ server at %s:%s" % (servername, portnum))
        self.set_server_documentation(documentation)
        self.__is_shut_down = threading.Event()
        self.__running = False

    def server_close(self):
        if self.__running:
            self.__running = False
            self.__is_shut_down.wait()
        DocXMLRPCServer.DocXMLRPCServer.server_close(self)

    def get_request(self):
        """Overridden in order to set so_keepalive on client
        sockets."""

        (conn, addr) = self.socket.accept()
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

        return (conn, addr)

    def serve_forever(self):
        """Handle one request at a time until doomsday."""
        self.__running = True
        self.__is_shut_down.clear()
        while self.__running:
            # initialize r to an empty list - identical behaviour to a timeout
            r = []
            try:
                r, w, e = select.select([self.socket], [], [], self.__timeout)
            except select.error, err:
                # ignore interrupted system calls
                if err[0] == 4:
                    continue
                # errno 9: Bad file descriptor
                if err[0] != 9:
                    traceback.print_exc()
                break
            if r:
                self.handle_request()
        self.__is_shut_down.set()


class RPCStat(object):
    "Class for accumulating statistics about an RPC call"
    def __init__(self):
        self.n = 0
        self.min = None
        self.max = None
        self.sum = 0.
        self.sumsq = 0.

    def tally(self, tdel):
        """Add a point to the statistics, keeping min/max, sum and sum
        of the squares for max/min/average/rms
        """
        secs = tdel.seconds + tdel.microseconds * 1.E-6
        self.n += 1

        self.min = min(secs, self.min)
        self.max = max(secs, self.max)

        self.sum += secs
        self.sumsq += secs * secs

    def summaries(self):
        """Generate some additional statistics, ie average and rms"""
        try:
            avg = self.sum / self.n
            # rms = sqrt(x_squared-avg - x-avg-squared)
            x2avg = self.sumsq / self.n
            xavg2 = avg * avg
            try:
                rms = math.sqrt(x2avg - xavg2)
            except:
                rms = None

            return (self.n, self.min, self.max, avg, rms)
        except ZeroDivisionError:
            return None

    def report(self):
        """Return a string representation of the statistics in this class"""
        l = self.summaries()
        if l == None:
            return "No entries."
        (n, Xmin, Xmax, avg, rms) = l
        return "%d entries, min=%.4f max=%.4f, avg=%.4f, rms=%.4f" % (n,
                                                                      Xmin,
                                                                      Xmax,
                                                                      avg,
                                                                      rms)

if __name__ == "__main__":
    from DAQConst import DAQPort
    cl = RPCClient("localhost", DAQPort.CNCSERVER)
    for i in xrange(0, 10):
        cl.rpccall("rpc_ping")
    print cl.showStats()
