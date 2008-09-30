#!/usr/bin/env python

# CheckHubRPMs.py
# John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
# Started: Mon Dec  3 15:21:10 2007

import re, os

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()
                    
class RPMCheckException          (Exception):         pass
class BadRPMLineException        (RPMCheckException): pass
class RPMNotFoundException       (RPMCheckException): pass
class TooManyRPMResultsException (RPMCheckException): pass
class RPMMismatchException       (RPMCheckException): pass

def checkrpm(rpmfull, rpm):
    p = os.popen("rpm -qa "+rpm)
    lines = p.readlines()
    if len(lines) < 1: raise RPMNotFoundException(rpm)
    if len(lines) > 1: raise TooManyRPMResultsException(','.join(lines))
    result = lines[0].rstrip(os.linesep)
    if result != rpmfull: raise RPMMismatchException("%s != required(%s)" % \
                                                     (result, rpmfull))
    
def main():
    default_config_file = os.path.join(metaDir, "dash", "standard-domhub-rpms.txt")
    lines = file(default_config_file).readlines()
    ok = True
    for line in lines:
        if re.search('^\s*#', line): continue
        m = re.search('^\s*(\S+)', line)
        if m:
            rpmfull = m.group(1)
            m1 = re.search('^(\S+)-([^-]+)-([^-]+)$', rpmfull)
            if not m1:
                raise BadRPMLineException("Line '%s' is not a valid RPM" % rpmfull)
            rpm = m1.group(1)
            try:
                checkrpm(rpmfull, rpm)
            except RPMNotFoundException, e:
                print "RPM not found ('%s')" % str(e)
                ok = False
            except RPMMismatchException, e:
                print "RPM mismatch ('%s')" % str(e)
                ok = False
            except TooManyRPMResultsException, e:
                print "Too many RPM results ('%s')" % str(e)
                ok = False
    if ok:
        print "All required RPMs found."
    else:
        print "All required RPMs NOT found."
            

if __name__ == "__main__": main()

