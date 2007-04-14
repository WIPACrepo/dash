#!/usr/bin/env python

import socket

def getIP(remoteHost='1.2.3.4'):
    """
    Found this gem of a kludge at
    http://mail.python.org/pipermail/python-list/2005-January/300454.html

    Modified to take an optional remoteHost arg to get the IP address
    from *that* host's perspective.  This is needed at times when run
    on multi-homed hosts.  -ksb
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((remoteHost, 56))
    return s.getsockname()[0]
        
