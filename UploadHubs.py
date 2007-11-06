#!/usr/bin/env python

import optparse, signal, sys, threading, time
from os import environ, getpid
from os.path import abspath, isabs, join, exists

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if environ.has_key("PDAQ_HOME"):
    metaDir = environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add 'cluster-config' to Python library search path
#
sys.path.append(join(metaDir, 'cluster-config'))

from ClusterConfig import *
from ParallelShell import *

def hasNonZero(l):
    if not l: raise RuntimeError("List is empty!")
    for x in l:
        if x != 0: return True
    return False

class HubMux:
    def __init__(self,timeoutSec=None):
        self.timeoutSec = timeoutSec
        self.hubs    = []
        self.hubcmds = {}
        self.results = {}
        self.tmpFile = "/tmp/__hub_uploader.out"
        self.lock    = threading.Lock()
        self.threads = {}

    def runThread(self, hub):
        print "Running command for %s" % hub
        time.sleep(3)
        
    def add(self, hub, sshCmd):
        self.hubs.append(hub)
        self.hubcmds[hub] = "(ssh %s %s 2>&1) > %s" % (hub, sshCmd, self.tmpFile)
        
    def done(self, hub):
        if self.threads.has_key(hub) and self.threads[hub].isAlive(): return False
        return True

    def watcher(self):
        while True:
            allDone = True
            for hub in self.hubs:
                print "Hub %s: " % hub,
                if self.done(hub):
                    print "Done"

                else:
                    allDone = False
                    print "Waiting..."
            if allDone: break
            time.sleep(1)
    
    def start(self):
        for hub in self.hubs:
            print "Launching:"
            print self.hubcmds[hub]
            self.threads[hub] = threading.Thread(target=self.runThread, args=(hub, ))
            self.threads[hub].start()
            self.watchThread = threading.Thread(target=self.watcher)
            self.watchThread.start()
            
    def results(self, hub): return ""
                
def main():
    p = optparse.OptionParser(usage="usage: %prog [options] <releasefile>")
    p.add_option("-c", "--config-name",  action="store", type="string",
                 dest="clusterConfigName",
                 help="Cluster configuration name, subset of deployed configuration.")
    p.add_option("-q", "--quiet",        action="store_true",           dest="quiet",
                 help="Run quietly")
    p.add_option("-v", "--verbose",      action="store_true",           dest="verbose",
                 help="Be chatty")
    p.add_option("-n", "--dry-run",      action="store_true",           dest="dryRun",
                 help="Don't run rsyncs, just print as they would be run (disables quiet)")
    p.set_defaults(clusterConfigName = None,
                   quiet             = False,
                   verbose           = False,
                   dryRun            = False)
    opt, args = p.parse_args()

    if len(args) < 1:
        p.error("An argument is required!")
        raise SystemExit

    releaseFile = args[0]

    # Make sure file exists
    if not exists(releaseFile):
        print "Release file %s doesn't exist!\n\n" % releaseFile
        print usage
        raise SystemExit

    clusterConfig = ClusterConfig(metaDir, opt.clusterConfigName)

    hublist = clusterConfig.getHubNodes()

    # Copy phase - copy mainboard release.hex file to remote nodes
    copySet = ParallelShell(parallel=True, dryRun=opt.dryRun, verbose=opt.verbose, timeout=300)
    
    remoteFile = "/tmp/release%d.hex" % getpid()
    for domhub in hublist:
        copySet.add("scp -q %s %s:%s" % (releaseFile, domhub, remoteFile))

    print "Copying %s to all hubs as %s..." % (releaseFile, remoteFile)
    copySet.start()
    try:
        copySet.wait(monitorIval=15)
    except KeyboardInterrupt, k:
        print "\nInterrupted."
        raise SystemExit
        
    if hasNonZero(copySet.getReturnCodes()):
        print copySet.getAllResults()
        raise RuntimeError("One or more parallel operations failed")

    # Upload phase - upload release
    #uploadSet = ParallelShell(parallel=True, dryRun=opt.dryRun, verbose=opt.verbose, timeout=1000)
    #counter = 0
    #hubHash = {}
    #for domhub in hublist:
    #    uploadSet.add("ssh %s UploadDOMs.py %s" % (domhub, remoteFile))
    #    hubHash[counter] = str(domhub)
    #    counter += 1

    mux = HubMux(timeoutSec=1000)
    for domhub in hublist:
        mux.add(domhub, "UploadDOMs.py %s" % remoteFile)

    print "Uploading %s on all hubs..." % remoteFile
    mux.start()
        
    #uploadSet.start()
    #monitorUpload(uploadSet, counter, hubHash)

    #raise SystemExit
    
    #uploadSet.wait(monitorIval=15)
    #if hasNonZero(uploadSet.getReturnCodes()):
    #    print uploadSet.getAllResults()
    #    print "One or more upload operations failed or were interrupted."
    #    print "DOMs are in an unknown state!"
    #    raise SystemExit

    # Cleanup phase - remove remote files from /tmp on hubs
    cleanUpSet = ParallelShell(parallel=True, dryRun=opt.dryRun, verbose=opt.verbose)
    for domhub in hublist:
        cleanUpSet.add("ssh %s /bin/rm -f %s" % (domhub, remoteFile))

    print "Cleaning up %s on all hubs..." % remoteFile
    cleanUpSet.start()
    cleanUpSet.wait()
    if hasNonZero(cleanUpSet.getReturnCodes()):
        print cleanUpSet.getAllResults()
        raise RuntimeError("One or more parallel operations failed")

    print "\n\nDONE."

if __name__ == "__main__": main()
