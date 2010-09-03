#!/usr/bin/env python

"""

UploadHubs.py

Upload DOM Mainboard release to all hubs *robustly*, giving full account
of any errors, slow DOMs, etc.

John Jacobsen, jacobsen@npxdesigns.com
Started November, 2007

"""

import datetime, optparse, os, popen2, re, select, signal, sys, threading, time

from DAQConfig import DAQConfigParser

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

def hasNonZero(l):
    if not l: raise RuntimeError("List is empty!")
    for x in l:
        if x != 0: return True
    return False

class ThreadableProcess:
    """
    Small class for a single instance of an operation to run concurrently
    w/ other instances (using ThreadSet)
    """
    def __init__(self, hub, cmd, verbose=False):
        self.cmd     = cmd
        self.hub     = hub
        self.fd      = None
        self.started = False
        self.done    = False
        self.doStop  = False
        self.thread  = None
        self.output  = ""
        self.lock    = None
        self.pop     = None
        self.verbose = verbose
        
    def _reader(self, hub, cmd):
        """
        Thread for starting, watching and controlling external process
        """
        if self.verbose: print "Starting '%s' on %s..." % (cmd, hub)
        self.lock    = threading.Lock()
        self.started = True
        self.pop = popen2.Popen4(cmd, 0)
        self.fd  = self.pop.fromchild
        fileno   = self.fd.fileno()
        while not self.doStop:
            ready = select.select([fileno], [], [], 1)
            if len(ready[0]) < 1: continue # Pick up stop signal
            self.lock.acquire()
            buf = os.read(fileno, 4096)
            self.output += buf
            self.lock.release()
            if buf == "": break
        if self.doStop:
            if self.verbose: print "Killing %s" % self.pop.pid
            os.kill(self.pop.pid, signal.SIGKILL)
        self.done    = True
        self.started = False

    def wait(self):
        """
        Wait until external process is done
        """
        while not self.done: time.sleep(0.3)
        if self.pop:
            if self.verbose: print "Waiting for %s" % self.pop.pid
            self.pop.wait()
    
    def start(self):
        """
        Start run thread for the desired external command
        """
        self.done = False
        if not self.thread:
            self.thread  = threading.Thread(target=self._reader, args=(self.hub, self.cmd, ))
            self.thread.start()

    def results(self):
        """
        Fetch results of external command in a thread-safe way
        """
        if self.lock: self.lock.acquire()
        r = self.output
        if self.lock: self.lock.release()
        return r

    def stop(self):
        """
        Signal control thread to stop
        """
        if self.verbose: print "OK, stopping thread for %s (%s)" % (self.hub, self.cmd)
        self.doStop = True

class DOM:
    """
    Small class to represent DOM states
    """
    def __init__(self, cwd, lines=None):
        self.cwd        = cwd
        self.lines      = []
        if lines:
            for l in lines: self.addData(l)
        self.failed     = False
        self.hasWarning = False
        self.done       = False
        self.version    = None
        
    def addData(self, line):
        self.lines.append(line)
        if re.search('FAIL', line):    self.failed = True
        if re.search('WARNING', line): self.hasWarning = True
        m = re.search('DONE \((\d+)\)', line)
        if m:
            self.done = True
            self.version = m.group(1)
        
    def lastState(self):
        try:
            return self.lines[-1]
        except KeyError:
            return None
        
    def hasWarning(self): return self.hasWarning
    def failed(self):     return self.failed
        
    def __str__(self):
        s = "DOM %s:\n" % self.cwd
        for l in self.lines:
            s += "\t%s\n" % l
        return s

class DOMCounter:
    """
    Class to represent and summarize output from upload script
    """
    def __init__(self, s):
        self.data    = s
        self.domDict = {}

        domList = re.findall('(\d\d\w): (.+)', self.data)
        for line in domList:
            cwd = line[0]
            dat = line[1]
            if not self.domDict.has_key(cwd):
                self.domDict[cwd] = DOM(cwd)
            self.domDict[cwd].addData(dat)
        
    def doms(self): return self.domDict.keys()
    
    def lastState(self, dom): return self.domDict[dom].lastState()
    
    def getVersion(self, dom):
        return self.domDict[dom].version
    
    def doneDomCount(self):
        n = 0
        for d in self.domDict:
            if self.domDict[d].done: n += 1
        return n

    def notDoneDoms(self):
        l = []
        for d in self.domDict:
            if not self.domDict[d].done: l.append(self.domDict[d])        
        return l
    
    def failedDoms(self):
        failed = []
        for d in self.domDict:
            if self.domDict[d].failed: failed.append(self.domDict[d])
        return failed

    def warningDoms(self):
        warns = []
        for d in self.domDict:
            if self.domDict[d].hasWarning: warns.append(self.domDict[d])
        return warns
    
    def versionCounts(self):
        versions = {}
        for d in self.domDict.keys():
            thisVersion = self.getVersion(d)
            if thisVersion == None: continue
            if not versions.has_key(thisVersion):
                versions[thisVersion] = 1
            else:
                versions[thisVersion] += 1
        return versions
    
    def __str__(self):
        s = ""
        # Show DOMs with warnings:
        warns = self.warningDoms()
        if len(warns) > 0:
            s += "\n%2d DOMs with WARNINGS:\n" % len(warns)
            for d in warns:
                s += str(d)
        # Show failed/unfinished DOMs:
        notdone = self.notDoneDoms()
        if len(notdone) > 0:
            s += "\n%2d DOMs failed or did not finish:\n" % len(notdone)
            for d in notdone:
                s += str(d)
        # Show versions
        vc = self.versionCounts()
        if len(vc) == 0:
            s += "NO DOMs UPLOADED SUCCESSFULLY!\n"
        elif len(vc) == 1:
            s += "Uploaded DOM-MB %s to %d DOMs\n" % (vc.keys()[0], self.doneDomCount())
        else:
            s += "WARNING: version mismatch\n"
            for version in vc:
                s += "%2d DOMs with %s: " % (vc[version], version)
                for d in self.domDict.keys():
                    if self.getVersion(d) == version: s += "%s " % d
                s += "\n"
        return s
    
class ThreadSet:
    """
    Lightweight class to handle concurrent ThreadableProcesses
    """
    def __init__(self, verbose=False):
        self.hubs    = []
        self.procs   = {}
        self.threads = {}
        self.output  = {}
        self.verbose = verbose
        
    def add(self, cmd, hub=None):
        if not hub: hub = len(self.hubs)
        self.hubs.append(hub)
        self.procs[hub] = ThreadableProcess(hub, cmd, self.verbose)
        
    def start(self):
        for hub in self.hubs:
            self.procs[hub].start()

    def stop(self):
        for hub in self.hubs:
            self.procs[hub].stop()

    def wait(self):
        for hub in self.hubs:
            self.procs[hub].wait()

class HubThreadSet(ThreadSet):
    """
    Class to watch progress of uploads and summarize details
    """
    def __init__(self, verbose=False, watchPeriod=15, stragglerTime=240):
        ThreadSet.__init__(self, verbose)
        self.watchPeriod   = watchPeriod
        self.stragglerTime = stragglerTime
        
    def summary(self):
        r = ""
        failedDOMs  = 0
        warningDOMs = 0
        doneDOMs    = 0
        for hub in self.hubs:
            dc = DOMCounter(self.procs[hub].results())
            domCount = len(dc.doms())
            done     = dc.doneDomCount()
            doneDOMs    += done
            warningDOMs += len(dc.warningDoms())
            failedDOMs  += (domCount-done) # Include DOMs which didn't complete
            r += "%s: %s\n" % (hub, str(dc).strip())
        r += "%d DOMs uploaded successfully" % doneDOMs
        r += " (%d with warnings)\n" % warningDOMs
        r += "%d DOMs did not upload successfully\n" % failedDOMs
        return r
        
    def watch(self):
        tstart = datetime.datetime.now()
        while True:
            t = datetime.datetime.now()
            dt = t-tstart
            if dt.seconds > 0 and dt.seconds % self.watchPeriod == 0:
                nDone = 0
                doneDomCount = 0
                for hub in self.hubs:
                    dc = DOMCounter(self.procs[hub].results())
                    doneDomCount += dc.doneDomCount()
                    if self.procs[hub].done:
                        nDone += 1
                    nd = dc.notDoneDoms()
                    if nd and dt.seconds > self.stragglerTime:
                        print "Waiting for %s:" % hub
                        for notDone in dc.notDoneDoms():
                            print "\t%s: %s" % (notDone.cwd, notDone.lastState())
                if nDone == len(self.hubs): break
                print "%s Done with %d of %d hubs (%d DOMs)." % (str(datetime.datetime.now()),
                                                                 nDone,
                                                                 len(self.hubs),
                                                                 doneDomCount)
            time.sleep(1)
            
def testProcs():
    ts = HubThreadSet(verbose=True)
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
        ts.add("./simUpload.py", hub)
    ts.start()
    try:
        ts.watch()
    except KeyboardInterrupt:
        ts.stop()
    
def main():

    usage = "usage: %prog [options] <releasefile>"
    p = optparse.OptionParser(usage=usage)
    p.add_option("-c", "--config-name", type="string", dest="clusterConfigName",
                 action="store", default=None,
                 help="Cluster configuration name, subset of deployed" +
                 " configuration.")
    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Be chatty")
    p.add_option("-f", "--skip-flash", dest="skipFlash",
                 action="store_true", default=False,
                 help="Don't actually write flash on DOMs -" +
                 " just 'practice' all other steps")
    p.add_option("-s", "--straggler-time", type="int",  dest="stragglerTime",
                 action="store", default=240,
                 help="Time (seconds) to wait before reporting details" +
                 " of straggler DOMs (default: 240)")
    p.add_option("-w", "--watch-period", type="int",  dest="watchPeriod",
                 action="store", default=15,
                 help="Interval (seconds) between status reports during" +
                 " upload (default: 15)")

    opt, args = p.parse_args()

    if len(args) < 1:
        p.error("An argument is required!")
        raise SystemExit

    releaseFile = args[0]

    # Make sure file exists
    if not os.path.exists(releaseFile):
        print "Release file %s doesn't exist!\n\n" % releaseFile
        print usage
        raise SystemExit

    clusterConfig = \
        DAQConfigParser.getClusterConfiguration(opt.clusterConfigName)

    hublist = clusterConfig.getHubNodes()

    # Copy phase - copy mainboard release.hex file to remote nodes
    copySet = ThreadSet(opt.verbose)
    
    remoteFile = "/tmp/release%d.hex" % os.getpid()
    for domhub in hublist:
        copySet.add("scp -q %s %s:%s" % (releaseFile, domhub, remoteFile))

    print "Copying %s to all hubs as %s..." % (releaseFile, remoteFile)
    copySet.start()
    try:
        copySet.wait()
    except KeyboardInterrupt:
        print "\nInterrupted."
        copySet.stop()
        raise SystemExit
        
    # Upload phase - upload release
    print "Uploading %s on all hubs..." % remoteFile

    uploader = HubThreadSet(opt.verbose, opt.watchPeriod, opt.stragglerTime)
    for domhub in hublist:
        f   = opt.skipFlash and "-f" or ""
        cmd = "ssh %s UploadDOMs.py %s -v %s" % (domhub, remoteFile, f)
        uploader.add(cmd, domhub)
        
    uploader.start()
    try:
        uploader.watch()
    except KeyboardInterrupt:
        print "Got keyboardInterrupt... stopping threads..."
        uploader.stop()
        try:
            uploader.wait()
            print "Killing remote upload processes..."
            killer = ThreadSet(opt.verbose)
            for domhub in hublist:
                killer.add("ssh %s killall -9 UploadDOMs.py" % domhub, domhub)
            killer.start()
            killer.wait()
        except KeyboardInterrupt:
            pass            
        
    # Cleanup phase - remove remote files from /tmp on hubs
    cleanUpSet = ThreadSet(opt.verbose)
    for domhub in hublist:
        cleanUpSet.add("ssh %s /bin/rm -f %s" % (domhub, remoteFile))

    print "Cleaning up %s on all hubs..." % remoteFile
    cleanUpSet.start()
    try:
        cleanUpSet.wait()
    except KeyboardInterrupt:
        print "\nInterrupted."
        cleanUpSet.stop()
        raise SystemExit

    
    print "\n\nDONE."
    print uploader.summary()
    
if __name__ == "__main__": main()
