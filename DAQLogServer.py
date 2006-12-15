#!/usr/bin/env python

# DAQLogServer.py
# jaacobsen@npxdesigns.com
# Dec. 2006
#
# Use SocketLogger to log all incoming log packets to a single file

from DAQLog import SocketLogger
from time import sleep
from sys import argv

if __name__ == "__main__":

    if len(argv) < 2:
        print "Usage: DAQLogServer.py <file> <port>"
        raise SystemExit

    logfile = argv[1]
    port    = int(argv[2])

    print "Will log messages arriving on port %d to %s." % (port, logfile)
    
    try:
        logger = SocketLogger(port, "all-components", logfile)
        logger.startServing()
        try:
            while 1:
                sleep(1)
        except:
            pass
    finally:
        logger.stopServing() # This tells thread to stop if KeyboardInterrupt
                             # If you skip this step you will be unable to control-C
                             
    
