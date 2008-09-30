#!/usr/bin/env python

#
# DAQRPC - Python wrapper for pDAQ RPC calls
#          Implemented with XML-RPC
#
# J. Jacobsen, for UW-IceCube 2006-2007
#

import DocXMLRPCServer
import xmlrpclib
import socket
import datetime
import math

class RPCClient(xmlrpclib.ServerProxy):

    "number of seconds before RPC call is aborted"
    TIMEOUT_SECS = 120

    "Generic class for accessing methods on remote objects"
    "WARNING: instantiating RPCClient sets socket default timeout duration!"
    def __init__(self, servername, portnum, verbose=0):
        
        self.servername = servername
        self.portnum    = portnum
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # !!!!!! Warning - this is ugly !!!!!!!
        # !!!! but no other way in XMLRPC? !!!!
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        socket.setdefaulttimeout(self.TIMEOUT_SECS)
        xmlrpclib.ServerProxy.__init__(self,
                                       "http://%s:%s" % (self.servername, self.portnum), verbose=verbose)
        self.statDict = { }

    def showStats(self):
        "Return string representation of accumulated statistics"
        if self.nCalls() == 0: return "None"
        r = ""
        for x in self.callList():
            r += "%25s: %s\n" % (x, self.statDict[x].report())
        return r

    def nCalls(self):
        "Return number of invocations of RPC method"
        return len(self.statDict)
    
    def callList(self):
        "Return list of registered methods"
        return self.statDict.keys()
        
    def rpccall(self, method, *rest):
        "Wrapper to benchmark speed of various RPC calls"
        if not self.statDict.has_key(method):
            self.statDict[method] = RPCStat()
        tstart = datetime.datetime.now()
        reststr = ""
        if len(rest) > 0:
            reststr += `rest[0]`
            for x in rest[1:]:
                reststr += ",%s" % `x`
        code = "self.%s(%s)" % (method, reststr)
        try:
            result = eval(code)
            self.statDict[method].tally(datetime.datetime.now()-tstart)
        except Exception:
            self.statDict[method].tally(datetime.datetime.now()-tstart)
            raise
        
        return result
        
class RPCServer(DocXMLRPCServer.DocXMLRPCServer):
    "Generic class for serving methods to remote objects"
    # also inherited: register_function
    allow_reuse_address = True
    def __init__(self, portnum, servername="localhost", documentation="DAQ Server"):
        self.servername = servername
        self.portnum    = portnum
        DocXMLRPCServer.DocXMLRPCServer.__init__(self, ('', portnum), logRequests=False)
        self.set_server_title("Server Methods")
        self.set_server_name("DAQ server at %s:%s" % (servername, portnum))
        self.set_server_documentation(documentation)
        # Avoid "Address in use" errors:
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

class RPCStat:
    "Class for accumulating statistics about an RPC call"
    def __init__(self):
        self.n     = 0
        self.min   = None
        self.max   = None
        self.sum   = 0.
        self.sumsq = 0.

    def tally(self, tdel):
        secs = tdel.seconds + tdel.microseconds * 1.E-6
        self.n += 1
        if self.min == None or self.min > secs:
            self.min = secs
        if self.max == None or self.max < secs:
            self.max = secs
        self.sum += secs
        self.sumsq += secs*secs

    def summaries(self):
        if self.n == 0: return None
        avg = self.sum / self.n
        # rms = sqrt(x_squared-avg - x-avg-squared)
        x2avg = self.sumsq / self.n
        xavg2 = avg*avg
        try:
            rms = math.sqrt(x2avg - xavg2)
        except Exception:
            rms = None
        return (self.n, self.min, self.max, avg, rms)
    
    def report(self):
        l = self.summaries()
        if l == None: return "No entries."
        (n, Xmin, Xmax, avg, rms) = l
        return "%d entries, min=%.4f max=%.4f, avg=%.4f, rms=%.4f" % (self.n,
                                                                      self.min,
                                                                      self.max,
                                                                      avg,
                                                                      rms)

if __name__ == "__main__":
    cl = RPCClient("localhost", 8080)
    for i in xrange(0,10):
        cl.rpccall("rpc_ping")
    print cl.showStats()

