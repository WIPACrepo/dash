#!/usr/bin/env python

# RateCalc.py
# John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
# Started: Fri Nov 16 11:40:56 2007

import datetime
import time

class RateException(Exception): pass
class InsufficientEntriesException(RateException): pass
class ZeroTimeDeltaException(RateException): pass

class RateCalcEntry(object):
    def __init__(self, time, n):
        self.time = time; self.n = n
    def __repr__(self):
        return "RateCalcEntry[%s -> %s]" % (str(self.time), str(self.n))
    def __str__(self): return "%s: %s" % (self.time, self.n)
    
def dt(t0, t1): # Calculate absolute time delta in seconds from datetime objects
    d = t1-t0
    return d.days*86400 + d.seconds + 1.E-6*d.microseconds

class RateCalc(object):
    def __init__(self, interval=300., maxentries=1000):
        """
        Interval is the maximum time between rate bins, i.e. if 300 seconds,
        then use the most recent five minutes to calculate the rate
        """
        self.interval   = interval
        self.maxentries = maxentries
        self.entries    = []

    def __str__(self):
        return "RateCalc[intvl %d max %d %s]" % \
            (self.interval, self.maxentries, str(self.entries))

    def reset(self): self.entries = []
    
    def add(self, time, count):
        """
        Add new entry to list, but don't let list exceed self.maxentries
        """
        while len(self.entries) >= self.maxentries:
            self.entries.pop(0)
        self.entries.append(RateCalcEntry(time, count))
        
    def rate(self):
        """
        Get latest rate value.  Raise exceptions if time difference
        is zero or not enough entries
        """
        # Find the desired bin by walking back in time.  This is a bit crude but
        # we don't need to worry about performance for the target application
        # (DAQRun rate calculation)
        recent = self.entries[-1]
        entry  = None
        dtsec  = 0
        for bin in range(-1, -1-len(self.entries), -1):
            entry = self.entries[bin]
            dtsec = dt(entry.time, recent.time)
            if dtsec > self.interval: break
        if entry is None: raise InsufficientEntriesException()
        if dtsec == 0: raise ZeroTimeDeltaException()
        return (recent.n - entry.n)/dtsec
    
def main():
    """
    Test by running at 1 Hz for 10 seconds, then hammering it for one second, then
    baseline at 1 Hz again -- printed rate goes high for "interval" seconds as
    desired
    """
    rc = RateCalc(interval=5)
    count = 0
    rc.add(datetime.datetime.now(), count)
    for i in range(0, 10):
        time.sleep(1)
        count += 1
        rc.add(datetime.datetime.now(), count)
        print rc.rate()

    count += 1000
    time.sleep(1)
    rc.add(datetime.datetime.now(), count)
    print rc.rate()

    for i in range(0, 10):
        time.sleep(1)
        count += 1
        rc.add(datetime.datetime.now(), count)
        print rc.rate()
    
if __name__ == "__main__": main()

