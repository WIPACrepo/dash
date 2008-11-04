#!/usr/bin/env python

import tarfile
import datetime
from sys import argv
from os import popen, listdir, chdir, link, unlink, stat, chmod
from time import sleep
from os.path import basename, exists
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
    targetDir             = "/mnt/data/pdaqlocal"
    chdir(targetDir)
    # Make sure I'm not already running - so I can auto-restart out of crontab
    if(checkForRunningProcesses(basename(argv[0]))): raise SystemExit
    
    while True:
        try:
            # Get list of available files, matching target tar pattern:
            allFiles = listdir(targetDir)
            matchingFiles = []
            for f in allFiles:
                if isTargetFile(f): 
                    matchingFiles.append(f)
                
            matchingFiles.sort(lambda x, y: (cmp(stat(x)[8], stat(y)[8])))
            
            # Make list for tarball - restrict total number of files
            filesToTar = []
            for f in matchingFiles:
                if not isTargetFile(f): continue # Redundant
                filesToTar.append(f)
                if len(filesToTar) >= MAX_FILES_PER_TARBALL: break
            
            if len(filesToTar) == 0:
                raise SystemExit
            
            print filesToTar
            t = datetime.datetime.now()
            dateTag  = "%03d_%04d%02d%02d_%02d%02d%02d_%06d" % (0, t.year, t.month, t.day,
                                                                t.hour, t.minute, t.second, 0)
            spadeTar = "SPS-pDAQ-2ndBld-%s.dat.tar" % dateTag
            moniLink = "SPS-pDAQ-2ndBld-%s.mon.tar" % dateTag
            snLink   = "SPS-pDAQ-2ndBld-%s.sn.tar"  % dateTag
            moniSem  = "SPS-pDAQ-2ndBld-%s.msem"    % dateTag
            spadeSem = "SPS-pDAQ-2ndBld-%s.sem"     % dateTag

            # Create spade tarball
            print spadeTar
            
            # Duplicate file: wait for a new second, recalculate everything:
            if exists(spadeTar): sleep(1); continue 
            
            tarball = tarfile.open(spadeTar, "w")
            for toAdd in filesToTar:
                print toAdd
                tarball.add(toAdd)
            tarball.close()
            print "Done."
            
            # Create moni hard link
            print moniLink
            link(spadeTar, moniLink)

            # Create sn hard link
            print snLink
            link(spadeTar, snLink)
            chmod(snLink, 0666); # So that Alex can delete if he's not running as pdaq
            
            # Create spade .sem
            f = open(spadeSem, "w"); f.close()

            # Create monitoring .msem
            f = open(moniSem, "w"); f.close()

            # Clean up tar'ed files
            for toAdd in filesToTar:
                print "Removing %s..." % toAdd
                unlink(toAdd)
                
        except KeyboardInterrupt: break
        #except: pass

if __name__ == "__main__": main()
