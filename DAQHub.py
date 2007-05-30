#!/usr/bin/env python

# John Jacobsen
# john@mail.npxdesigns.com
# NPX Designs, Inc. for UW-IceCube

class DAQHub:
    def __init__(self): pass
    def somePairsPowered(self):
        "Spider through /proc/driver/domhub/card?/pair?/pwr and see who's on"
        return False
    
    def powerOn(self):
        "Use /proc/driver/domhub/pwrall proc file to power on all DOMs"
        print "Powering on DOMs!"
        pass
    
    def goToIceboot(self):
        "(Threaded): send 'r' to all DOMs to put in iceboot (if in configboot)"
        pass
    
    def getHubStatus(self):
        "Return number of pairs plugged, powered and DOMs communicating, in iceboot"
        return (0,0,0,0)

def main():
    hub = DAQHub()
    if not hub.somePairsPowered():
        hub.powerOn()
    hub.goToIceboot()
    (numPairsPlugged,
     numPairsPowered,
     numDOMsCommunicating,
     numDOMsInIceboot) = hub.getHubStatus()
    print "Pairs: %d plugged, %d on" % (numPairsPlugged, numPairsPowered)
    print "DOMs:  %d communicating, %d in iceboot" % (numDOMsCommunicating, numDOMsInIceboot)

if __name__ == "__main__": main()

