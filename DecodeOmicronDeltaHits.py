#!/usr/bin/env python

"""
decodehits.py
John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
Started: Thu Feb  7 05:26:15 2008
"""

import optparse, struct
from icecube.daq.util import nextHit

def decode_hits(f):
    """
    Decode delta-compressed hits as they come out of Kael's Omicron
    """
    while True:
        hit = nextHit(f)
        if hit is None: break
        if hit.atwd_avail: hit.decode_waveforms()
        print "id=0x%s trig=0x%x chip=%d gt=%s" % (hit.mbid, hit.trigger,
                                                 hit.atwd_chip, str(hit.utc))
        for chan in range(2, -1, -1):
            bins = hit.atwd[chan]
            if bins:
                wfstr = " ".join([str(x) for x in bins])
                print "atwd%d %s" % (chan, wfstr)
                break
    
def main():
    """
    Print decoded hit output for all files given on command line
    """
    p = optparse.OptionParser()
    opt, args = p.parse_args()
    for f in args:
        decode_hits(open(f))

if __name__ == "__main__": main()

