#!/usr/bin/env python

# CheckHubRPMs.py
# John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
# Started: Mon Dec  3 15:21:10 2007

import optparse, re

class BadRPMLineException(Exception): pass

def checkrpm(rpmfull, rpm):
    print rpmfull, rpm

def main():
    default_config_file = "standard-domhub-rpms.txt"
    lines = file(default_config_file).readlines()
    for line in lines:
        if re.search('^\s*#', line): continue
        m = re.search('^\s*(\S+)', line)
        if m:
            rpmfull = m.group(1)
            m1 = re.search('(.+?)-\d', line)
            if not m1:
                raise BadRPMLineException("Line '%s' is not a valid RPM" % line)
            rpm = m1.group(1)

            checkrpm(rpmfull, rpm)

if __name__ == "__main__": main()

