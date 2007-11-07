#!/usr/bin/env python

# simUpload.py
# John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
# Started: Tue Nov  6 14:38:09 2007

import time, random

def main():
    speed = random.randint(1, 10)
    time.sleep(speed)
    for c in range(0, 8):
        for w in range(0, 4):
            for d in ('A', 'B'):
                time.sleep(random.randint(0, 3)/100)
                release = 431
                if random.randint(0, 60*9) < 3: release = 426
                if random.randint(0, 60*9) < 1:
                    print "%d%d%s: Bad stuff happened." % (c,w,d)
                    print "Really, really bad stuff, I mean."
                    print "%d%d%s: FAIL" % (c,w,d)
                else:
                    if random.randint(0, 60*9) < 3:
                        print "%d%d%s: Warning:" % (c,w,d)
                        print "Something possibly bad happened."
                    if random.randint(0, 60*9) < 4:
                        time.sleep(speed*3) # Simulate slow DOM
                    print "%d%d%s: DONE (%d)" % (c,w,d, release)

if __name__ == "__main__": main()

