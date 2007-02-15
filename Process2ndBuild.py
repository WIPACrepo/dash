#!/usr/bin/env python

import tarfile
import datetime
from sys import argv
from os import popen, listdir, chdir, link, unlink, stat
from time import sleep
from os.path import basename, join, exists
from re import search

def checkForRunningProcesses(progname):
    c = popen("pgrep -fl 'python .+%s'" % progname, "r")
    l = c.read()
    num = len(l.split('\n'))
    if num < 3: return False # get extra \n at end of command
    return True

def isTargetFile(f):
    match = search(r'\w+_\d+_\d+_\d+_\d+\.dat', f)
    if match: return True
    return False

def main():
    MAX_FILES_PER_TARBALL = 50
    SLEEP_INTERVAL        = 60*5
    targetDir             = "/mnt/data/pdaqlocal"
    chdir(targetDir)
    # Make sure I'm not already running - so I can auto-restart out of crontab
    if(checkForRunningProcesses(basename(argv[0]))): raise SystemExit
    
    while True:
        try:
            # Get list of available files
            allfiles   = listdir(targetDir)
            allfiles.sort(lambda x, y: (cmp(stat(x)[8],stat(y)[8])))
            
            # Make list for tarball - restrict total number of files
            filesToTar = []
            for f in allfiles:
                # print f
                if not isTargetFile(f): continue
                filesToTar.append(f)
                if len(filesToTar) >= MAX_FILES_PER_TARBALL: break
            
            if len(filesToTar) == 0:
                sleep(SLEEP_INTERVAL)
                continue
                
            print filesToTar
            t = datetime.datetime.now()
            dateTag  = "%03d_%04d%02d%02d_%02d%02d%02d_%06d" % (0, t.year, t.month, t.day,
                                                                t.hour, t.minute, t.second, 0)
            spadeTar = "SPS-pDAQ-2ndBld-%s.dat.tar" % dateTag
            moniLink = "SPS-pDAQ-2ndBld-%s.mon.tar" % dateTag
            spadeSem = "SPS-pDAQ-2ndBld-%s.sem"     % dateTag
            moniSem  = "SPS-pDAQ-2ndBld-%s.msem"    % dateTag

            # Create spade tarball
            print spadeTar
            if exists(spadeTar): sleep(1); continue # Duplicate file: wait for a new second, recalculate everything
            
            tarball = tarfile.open(spadeTar, "w")
            for toAdd in filesToTar:
                print toAdd
                tarball.add(toAdd)
            tarball.close()
            print "Done."
            
            # Create moni hard link
            print moniLink
            link(spadeTar, moniLink)
            
            # Create spade .sem
            f = open(spadeSem, "w"); f.close()
            
            # Create moni .sem
            f = open(moniSem, "w"); f.close()

            # Clean up tar'ed files
            for toAdd in filesToTar:
                print "Removing %s..." % toAdd
                unlink(toAdd)
                
        except KeyboardInterrupt, k: break
        #except: pass

if __name__ == "__main__": main()
