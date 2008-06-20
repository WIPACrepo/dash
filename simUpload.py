#!/usr/bin/env python

# simUpload.py
# John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
# Started: Tue Nov  6 14:38:09 2007

import time, random

states = ("SOFTBOOT1",
          "OPEN",
          "CHECK_ICEBOOT1",
          "ISET",
          "SENDING (23%)",
          "CHECK_ICEBOOT2",
          "CHECK_STACK",
          "CHECK_MD5SUM",
          "GUNZIP",
          "INSTALL",
          "SOFTBOOT2",
          "CHECK_VERSION",
          "DONE")

targetVersion = 431
altVersion    = 426

class DOM:
    def __init__(self, c, w, d):
        self.c = c
        self.w = w
        self.d = d
        self.state = 0
        self.done = False
        self.version = None
                
    def nextState(self):
        self.state += 1
        time.sleep(0.001)
        if self.state == len(states): self.done = True
        
    def stateStr(self):
        version = targetVersion
        if random.randint(0, 1000) < 2: version = altVersion
        s = states[self.state]
        if s != "DONE": return s
        if random.randint(0, 1000) < 2: return "FAIL (test)"
        return "%s (%d)" % (states[self.state], version)
    
def main():
    doms = {}
    for c in range(0, 8):
        for w in range(0, 4):
            for d in ('A', 'B'):
                doms[(c,w,d)] = DOM(c,w,d)
                                
    while True:
        for c in range(0, 8):
            for w in range(0, 4):
                for d in ('A', 'B'):
                    allDone = True
                    if not doms[(c,w,d)].done:
                        print "%d%d%s: %s" % (c,w,d,doms[(c,w,d)].stateStr())
                        doms[(c,w,d)].nextState()
                        allDone = False
                    if allDone: return
                        
        


#                 continue
                
#                 time.sleep(random.randint(0, 3)/100)
#                 release = 431
#                 if random.randint(0, 60*9) < 3: release = 426
#                 if random.randint(0, 60*9) < 1:
#                     print "%d%d%s: Bad stuff happened." % (c,w,d)
#                     print "Really, really bad stuff, I mean."
#                     print "%d%d%s: FAIL" % (c,w,d)
#                 else:
#                     if random.randint(0, 60*9) < 3:
#                         print "%d%d%s: Warning:" % (c,w,d)
#                         print "Something possibly bad happened."
#                     if random.randint(0, 60*9) < 4:
#                         time.sleep(speed*3) # Simulate slow DOM
#                     print "%d%d%s: DONE (%d)" % (c,w,d, release)

if __name__ == "__main__": main()

