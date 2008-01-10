#!/usr/bin/env python

import os, sys
from datetime import date, datetime, timedelta
from icecube.daq.nicknames import Nicknames
from icecube.daq.payload import decode_payload, MonitorRecordPayload
from icecube.daq.monitoring import HardwareMonitorRecord
from getopt import getopt

MBID = 0
PRODID = 1
OMKEY = 3
NICKNAME = 2

domid = MBID
year  = date.today().year
time  = True

opts, args = getopt(sys.argv[1:], 'DKNYU:h')
for o, a in opts:
    if o == '-D':
        # emit the DOMID
        domid = PRODID
    elif o == '-K':
        domid = OMKEY
    elif o == '-N':
        domid = NICKNAME
    elif o == '-h':
        print >>sys.stderr, "usage :: DAQDumpMoni.py [-D | -K | -N ] <inputs ...>"
        sys.exit(1)
    elif o == '-Y':
        year = int(a)
    elif o == '-U':
        time = False

T0 = datetime(year, 1, 1)

if domid != MBID:
    if "NICKNAMES" not in os.environ:
        print >>sys.stderr, "please point NICKNAMES environment variable " + \
            "to nicknames.txt file."
        sys.exit(1)
    nick = Nicknames(os.environ["NICKNAMES"])
    
for arg in args:
    f = open(arg)
    while 1:
        p = decode_payload(f)
        if p is None: break
        if isinstance(p, MonitorRecordPayload):
            m = p.rec
            if isinstance(m, HardwareMonitorRecord):
                utc = m.timestamp
                if time: utc = T0 + timedelta(seconds=1.0E-10*utc)
                mbid = m.domid
                name = mbid
                try:
                    if domid != MBID: name = nick.lookup(mbid)[domid]
                except KeyError:
                    pass
                spe = m.getSPERate()
                hv  = m.getHVMonitor()
                kpa = '*'
                try:
                    kpa = '%.1f' % m.getPressure()
                except ZeroDivisionError:
                    pass
                print utc, name, spe, hv, kpa
                
