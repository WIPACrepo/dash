#!/usr/bin/env python

import DocXMLRPCServer
import xmlrpclib
import socket

# Generic class for accessing methods on remote objects
class RPCClient(xmlrpclib.ServerProxy):
    "WARNING: instantiating RPCClient sets socket default timeout to 10 seconds!"
    def __init__(self, servername, portnum):
        
        self.servername = servername
        self.portnum    = portnum
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # !!!!!! Warning - this is ugly !!!!!!!
        # !!!! but no other way in XMLRPC? !!!!
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        socket.setdefaulttimeout(10)            #set the timeout to 10 seconds
        xmlrpclib.ServerProxy.__init__(self,
                                       "http://%s:%s" % (self.servername, self.portnum))
        
# Generic class for serving methods to remote objects
class RPCServer(DocXMLRPCServer.DocXMLRPCServer):
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
