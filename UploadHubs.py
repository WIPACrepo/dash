#!/usr/bin/env python

import optparse, signal, sys, threading, time, select
from os import environ, getpid, popen
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

class ThreadableProcess:
    def __init__(self, hub, cmd):
        self.cmd     = cmd
        self.hub     = hub
        self.fd      = None
        self.started = False
        self.done    = False
        self.thread  = None
        self.output  = ""
        self.lock    = None
        
    def _reader(self, hub, cmd):
        self.lock    = threading.Lock()
        self.started = True
        self.fd = popen(cmd)
        for r in self.fd:
            self.lock.acquire()
            self.output += r
            self.lock.release()
        self.done    = True
        self.started = False
        
    def start(self):
        self.done = False
        if not self.thread:
            self.thread  = threading.Thread(target=self._reader, args=(self.hub, self.cmd, ))
            self.thread.start()

    def results(self):
        if self.lock: self.lock.acquire()
        r = self.output
        if self.lock: self.lock.release()
        return r

class DOMCounter:
    def __init__(self, s):
        self.data = s

    def doneDOMs(self):
        return re.findall('(\d)(\d)(\w): DONE \((\d+)\)', self.data)
    
    def versionHash(self):
        list = self.doneDOMs()
        h = {}
        for dom in list:
            if not h.has_key(dom[3]): h[dom[3]] = 1 # There's a better way to do this, but I forgot...
            else: h[dom[3]] += 1
        return h

    def domCount(self):
        return len(self.doneDOMs())
    
    def failList(self):
        list = re.findall('(\d)(\d)(\w): FAIL', self.data)
        return ["%s%s%s" % dom for dom in list]

    def warnText(self):
        txt = re.sub('\d\d\w: DONE \(\d+\)\s*','',self.data)
        return txt
        
    def __str__(self):
        s = "Versions: "
        v = self.versionHash()
        l = ["%s (%s DOMs)" % (k, v[k]) for k in v.keys()]
        if len(l) == 0:
            s += "None\n"
        else:
            s += "; ".join(l)
        f = self.failList()
        if f or self.warnText() != "":
            s += "\nFailures: "
            if f:
                s += " ".join(f)+"\n"
            else:
                s += "None\n"
            s += "--------------------------\n"
            s += self.warnText()
            s += "--------------------------\n\n"
        return s
    
class ThreadSet:
    def __init__(self):
        self.hubs    = []
        self.procs   = {}
        self.threads = {}
        self.output  = {}
        
    def add(self, hub, cmd):
        self.hubs.append(hub)
        self.procs[hub] = ThreadableProcess(hub, cmd)
        
    def start(self):
        for hub in self.hubs:
            self.procs[hub].start()

    def watch(self):
        while True:
            nDone = 0
            domCount = 0
            for hub in self.hubs:
                if self.procs[hub].done:
                    nDone += 1
                    domCount += DOMCounter(self.procs[hub].results()).domCount()
            if nDone == len(self.hubs): break
            print "Done with %d of %d hubs (%d DOMs)." % (nDone, len(self.hubs), domCount)
            time.sleep(1)
        for hub in self.hubs:
            print "Hub", hub,
            print DOMCounter(self.procs[hub].results())
            
def testProcs():
    ts = ThreadSet()
    hublist = ["sps-ichub21",
               "sps-ichub29",
               "sps-ichub30",
               "sps-ichub38",
               "sps-ichub39",
               "sps-ichub40",
               "sps-ichub49",
               "sps-ichub50",
               "sps-ichub59"]
    for hub in hublist:
        ts.add(hub, "./simUpload.py")
    ts.start()
    ts.watch()
    
def main():
    testProcs()
    raise SystemExit

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

    print "Uploading %s on all hubs..." % remoteFile
        
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
