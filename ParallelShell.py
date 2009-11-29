#!/usr/bin/env python

# ParallelShell.py
# J. Jacobsen & K. Beattie, for UW-IceCube
# February, April, June 2007

"""
This module implements a means to run multiple shell commands in parallel.

See 'main' method at bottom for example usage.

Setting trace=True will allow the output of the commands to go to the
parent's terminal.  Calling ps.wait() will prevent the interpreter
from returning before the commands finish, otherwise the interpreter
will return while the commands continue to run;
"""

import re, subprocess, sys, time, os, os.path, datetime, signal

class TimeoutException(Exception): pass

class PCmd(object):
    """ Class for handling individual shell commands to be executed in
    parallel. """

    # class variable to guarantee unique filenames
    counter = 0
    
    def __init__(self, cmd, parallel=True, dryRun=False,
                 verbose=False, trace=False, timeout = None):
        """
        Construct a PCmd object with the given options:
        cmd - The command to run as a string.
        parallel - If True don't wait for command to return when
                   started, otherwise wait. Default: True
        dryRun   - If True, don't actually start command.  Only usefull
                   if verbose is also True. Default: False
        verbose  - If True, print command as they are run along with
                   process IDs and return codes. Default: False
        trace    - If True, use inherited parent's stdout and stderr.  If
                   False (the default) modifiy command string to redirect
                   stdout & err to /dev/null. 
        timeout  - If not None, number of seconds to wait before killing
                   process and raising a TimeoutException;
        """           
                   
        self.cmd        = cmd
        self.subproc    = None
        self.parallel   = parallel
        self.dryRun     = dryRun
        self.verbose    = verbose
        self.trace      = trace
        self.timeout    = timeout
        self.tstart     = None
        self.counter    = PCmd.counter
        self.pid        = os.getpid()
        self.outFile    = os.path.join("/","tmp","__pcmd__%d__%d.txt" % (self.pid,
                                                                         self.counter))
        self.output     = ""
        self.done       = False
        
        PCmd.counter += 1
        
    def __str__(self):
        """ Return info about this command, the pid used and return code. """
        state_str = "%s%s%s%s" % (self.parallel and 'p' or '', self.dryRun and 'd' or '',
                                  self.verbose and 'v' or '', self.trace and 't' or '')
        if self.subproc == None:  # Nothing started yet or dry run
            return "'%s' [%s] Not started or dry run" % (self.cmd, state_str)
        elif self.subproc.returncode == None:
            return "'%s' [%s] running as pid %d" % (self.cmd, state_str, self.subproc.pid)
        elif self.subproc.returncode < 0:
            return "'%s' [%s] terminated (pid was %d) by signal %d" % (self.cmd, state_str, self.subproc.pid, -self.subproc.returncode)
        else:
            return "'%s' [%s] (pid was %d) returned %d " % (self.cmd, state_str, self.subproc.pid, self.subproc.returncode)

    def start(self):
        """ Start this command. """
        self.tstart = datetime.datetime.now()

        # If not tracing, send both stdout and stderr to /dev/null
        if not self.trace:
            # Handle the case where the command ends in an '&' (silly
            # but we shouldn't break)
            if self.cmd.rstrip().endswith("&"):
                controlop = " "
            else:
                controlop = ";"
            self.cmd = "{ %s %c } >%s 2>&1" % (self.cmd, controlop, self.outFile)

        if self.subproc != None:
            raise RuntimeError("Attempt to start a running command!")

        # Create a Popen object for running a shell child proc to run the command
        if not self.dryRun:
            self.subproc = subprocess.Popen(self.cmd, shell=True)

        if self.verbose: print "ParallelShell: %s" % self

        # If not running in parallel, then wait for this command (at
        # least the shell) to return
        if not self.parallel: self.wait()
        
    def wait(self):
        """ Wait for the this command to return. """
        if self.done: return
        
        if self.subproc == None and not self.dryRun:
            raise RuntimeError("Attempt to wait for unstarted command!")

        if self.dryRun:  return

        if not self.timeout:
            self.subproc.wait()
        else: # Handle polling/timeout case
            status = self.subproc.poll()
            if status is None:
                if datetime.datetime.now()-self.tstart > datetime.timedelta(seconds=self.timeout):
                    # Kill child process - note that this may fail
                    # to clean up everything if child has spawned more proc's
                    os.kill(self.subproc.pid, signal.SIGKILL)
                    self.done = True
                    self.output += "TIMEOUT exceeded (%d seconds)" % self.timeout
                else:
                    return None # Not done yet - check back again        
            
        self.done = True
        if self.verbose: print "ParallelShell: %s" % self

        # Harvest results
        if self.trace:
            self.output += "Output not available: went to stdout!"
        else:
            try:
                for l in file(self.outFile): self.output += l
                os.unlink(self.outFile)
            except Exception, e:
                self.output += "Could not read or delete result file %s (%s)!" % (self.outFile, e)
            
        return

    def getResult(self): return self.output

class ParallelShell(object):
    """ Class to implement multiple shell commands in parallel. """
    def __init__(self, parallel=True, dryRun=False, verbose=False, trace=False, timeout=None):
        """ Construct a new ParallelShell object for managing multiple
        shell commands to be run in parallel.  The parallel, dryRun,
        verbose and trace options are identical to and used for each
        added PCmd object. """
        self.pcmds      = []
        self.parallel   = parallel
        self.dryRun     = dryRun
        self.verbose    = verbose
        self.trace      = trace
        self.timeout    = timeout
        
    def add(self, cmd):
        """ Add command to list of pending operations. """
        self.pcmds.append(PCmd(cmd, self.parallel, self.dryRun,
                               self.verbose, self.trace, self.timeout))
        return len(self.pcmds)-1 # Start w/ 0

    def start(self):
        """ Start all unstarted commands. """
        for c in self.pcmds:
            if c.subproc == None: c.start()

    def wait(self, monitorIval=None):
        """ Wait for all started commands to complete (or time out).  If the
        commands are backgrounded (or fork then return in their
        parent) then this will return immediately. """

        t     = datetime.datetime.now()
        t0    = t
        nToDo = len(self.pcmds)
        while True:
            stillWaiting = False
            nDone = 0
            for c in self.pcmds:
                if c.subproc:
                    if c.done:
                        nDone += 1
                    else:
                        c.wait() # Can raise TimeoutException
                        stillWaiting = True
                        
            if not stillWaiting: break
            if monitorIval and datetime.datetime.now()-t > datetime.timedelta(seconds=monitorIval):
                t = datetime.datetime.now()
                dt = t-t0
                print "%d of %d done (%s)." % (nDone, nToDo, str(dt))
            time.sleep(0.3)

    def showAll(self):
        """ Show commands and (if running or finished) with their
        process IDs and (if finished) with return codes. """
        for c in self.pcmds: print c

    def getCommand(self, job): return self.pcmds[job].cmd

    def getResult(self, job): return self.pcmds[job].getResult()
    
    def getAllResults(self):
        ret = ""
        for c in self.pcmds:
            ret += "Job: %s\nResult: %s\n" % (c, c.getResult())
        return ret
    
    def getReturnCodes(self):
        ret = []
        for c in self.pcmds:
            if c.subproc and c.done:
                ret.append(c.subproc.returncode)
            else:
                ret.append(0)
        return ret

    def system(self, cmd):
        return os.system(cmd)

def main():
    p = ParallelShell(timeout=5)
    jobs = []
    jobs.append(p.add("ls"))
    jobs.append(p.add("sleep 10"))
    jobs.append(p.add("sleep 4; echo done sleeping four"))
    p.start()
    p.wait()
    for job in jobs:
        print "Job %d: result %s" % (job, p.getResult(job))
    
if __name__ == "__main__": main()
