#!/usr/bin/env python

# DAQLogClient
# jacobsen@npxdesigns.com
# December, 2006
#
# Logger to write timestamped or raw data to a remote UDP logger (see DAQLog.py)

from datetime import datetime
from DAQRPC import RPCServer
import DAQLog
import socket

class DAQLogger(object): # Log to UDP socket, somewhere
    def __init__(self, node, port):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.connect((node, port))
    def write(self, s):
        "Write message to remote logger"
        self.socket.send(s)
    def write_ts(self, s):
        "Write time-stamped log msg to remote logger"
        self.socket.send("- - [%s] %s" % (datetime.now(), s))
    def close(self):
        "Shutdown socket to remote server - better do this to avoid stale sockets"
        self.socket.close()

class DAQLogClientTester(RPCServer):
    "Tests concurrent logging functionality - drive with DAQLog.py running as __main__"
    def __init__(self, portnum):
        RPCServer.__init__(self, portnum)
        self.register_function(self.log_to)
        self.register_function(self.close_log)
        self.logger = None
        self.instances = 0
        print "Hi, I'm a log test client on port %d" % portnum
    def log_to(self, node, port):
        print "Got request to log to %s %d" % (node, port)
        self.logger = DAQLogger(node, port)
        self.logger.write("Yo dude!  I'm here (%dth time)" % self.instances)
        self.logger.write("Form is the dreaming of substance")
        self.instances += 1
        return 1
    def close_log(self):
        print "Shutting down logger."
        self.logger.write("Ok, closing log, buh bye.")
        self.logger.close()
        self.logger = None
        return 1

if __name__ == "__main__":
    serv = DAQLogClientTester(6667)
    serv.serve_forever()
    
