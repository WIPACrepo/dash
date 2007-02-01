#!/usr/bin/env python

import socket

def getIP():
    """
    Found this gem of a kludge at
    http://mail.python.org/pipermail/python-list/2005-January/300454.html
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('1.2.3.4', 56))
    return s.getsockname()[0]
        
