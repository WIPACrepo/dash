#!/usr/bin/env python

"""

UploadHubs.py

Upload DOM Mainboard release to all hubs *robustly*, giving full account
of any errors, slow DOMs, etc.

John Jacobsen, jacobsen@npxdesigns.com
Started November, 2007

"""

from __future__ import print_function

import datetime
import os
import popen2
import re
import select
import signal
import sys
import threading
import time

from DAQConfig import DAQConfigParser
from DAQConfigExceptions import DAQConfigException


def has_non_zero(lst):
    if not lst:
        raise RuntimeError("List is empty!")
    for val in lst:
        if val != 0:
            return True
    return False


class ThreadableProcess(object):
    """
    Small class for a single instance of an operation to run concurrently
    w/ other instances (using ThreadSet)
    """
    def __init__(self, hub, cmd, verbose=False):
        self.cmd = cmd
        self.hub = hub
        self.fdesc = None
        self.started = False
        self.done = False
        self.do_stop = False
        self.thread = None
        self.output = ""
        self.lock = None
        self.pop = None
        self.verbose = verbose

    def _reader(self, hub, cmd):
        """
        Thread for starting, watching and controlling external process
        """
        if self.verbose:
            print("Starting '%s' on %s..." % (cmd, hub))

        self.lock = threading.Lock()
        self.started = True
        self.pop = popen2.Popen4(cmd, 0)
        self.fdesc = self.pop.fromchild
        fileno = self.fdesc.fileno()

        while not self.do_stop:
            ready = select.select([fileno], [], [], 1)
            if len(ready[0]) < 1:  # pylint: disable=len-as-condition
                continue  # Pick up stop signal
            with self.lock:
                buf = os.read(fileno, 4096)
                self.output += buf

            if buf == "":
                break

        if self.do_stop:
            if self.verbose:
                print("Killing %s" % self.pop.pid)
            os.kill(self.pop.pid, signal.SIGKILL)
        self.done = True
        self.started = False

    def wait(self):
        """
        Wait until external process is done
        """
        while not self.done:
            time.sleep(0.3)
        if self.pop is not None:
            if self.verbose:
                print("Waiting for %s" % self.pop.pid)
            self.pop.wait()

    def start(self):
        """
        Start run thread for the desired external command
        """
        self.done = False
        if not self.thread:
            self.thread = threading.Thread(target=self._reader,
                                           args=(self.hub, self.cmd, ))
            self.thread.start()

    def results(self):
        """
        Fetch results of external command in a thread-safe way
        """
        if self.lock:
            self.lock.acquire()

        rslt = self.output
        if self.lock:
            self.lock.release()

        return rslt

    def stop(self):
        """
        Signal control thread to stop
        """
        if self.verbose:
            print("OK, stopping thread for %s (%s)" % (self.hub, self.cmd))
        self.do_stop = True


class DOMState(object):
    """
    Small class to represent DOM states
    """
    def __init__(self, cwd, lines=None):
        self.cwd = cwd
        self.lines = []
        if lines:
            for line in lines:
                self.add_data(line)
        self._failed_ = False
        self._has_warning = False
        self.done = False
        self.version = None

    def add_data(self, line):
        self.lines.append(line)
        if re.search('FAIL', line):
            self._failed = True
        if re.search('WARNING', line):
            self._has_warning = True
        mtch = re.search(r'DONE \((\d+)\)', line)
        if mtch is not None:
            self.done = True
            self.version = mtch.group(1)

    def last_state(self):
        try:
            return self.lines[-1]
        except KeyError:
            return None

    @property
    def has_warning(self):
        return self._has_warning

    def failed(self):
        return self._failed

    def __str__(self):
        sstr = "DOM %s:\n" % self.cwd
        for line in self.lines:
            sstr += "\t%s\n" % line
        return sstr


class DOMCounter(object):
    """
    Class to represent and summarize output from upload script
    """
    def __init__(self, s):
        self.data = s
        self.dom_dict = {}

        dom_list = re.findall(r'(\d\d\w): (.+)', self.data)
        for line in dom_list:
            cwd = line[0]
            dat = line[1]
            if cwd not in self.dom_dict:
                self.dom_dict[cwd] = DOMState(cwd)
            self.dom_dict[cwd].add_data(dat)

    def doms(self):
        return list(self.dom_dict.keys())

    def last_state(self, dom):
        return self.dom_dict[dom].last_state()

    def get_version(self, dom):
        return self.dom_dict[dom].version

    def done_dom_count(self):
        num = 0
        for key in self.dom_dict:
            if self.dom_dict[key].done:
                num += 1
        return num

    def not_done_doms(self):
        not_done = []
        for key in self.dom_dict:
            if not self.dom_dict[key].done:
                not_done.append(self.dom_dict[key])
        return not_done

    def failed_doms(self):
        failed = []
        for key in self.dom_dict:
            if self.dom_dict[key].failed:
                failed.append(self.dom_dict[key])
        return failed

    def warning_doms(self):
        warns = []
        for key in self.dom_dict:
            if self.dom_dict[key].has_warning:
                warns.append(self.dom_dict[key])
        return warns

    def version_counts(self):
        versions = {}
        for key in list(self.dom_dict.keys()):
            this_version = self.get_version(key)
            if this_version is None:
                continue

            if this_version not in versions:
                versions[this_version] = 1
            else:
                versions[this_version] += 1
        return versions

    def __str__(self):
        outstr = ""
        # Show DOMs with warnings:
        warns = self.warning_doms()
        if len(warns) > 0:  # pylint: disable=len-as-condition
            outstr += "\n%2d DOMs with WARNINGS:\n" % len(warns)
            for dom in warns:
                outstr += str(dom)
        # Show failed/unfinished DOMs:
        notdone = self.not_done_doms()
        if len(notdone) > 0:  # pylint: disable=len-as-condition
            outstr += "\n%2d DOMs failed or did not finish:\n" % len(notdone)
            for dom in notdone:
                outstr += str(dom)
        # Show versions
        vcnt = self.version_counts()
        if len(vcnt) == 0:  # pylint: disable=len-as-condition
            outstr += "NO DOMs UPLOADED SUCCESSFULLY!\n"
        elif len(vcnt) == 1:
            outstr += "Uploaded DOM-MB %s to %d DOMs\n" % \
                (list(vcnt.keys())[0], self.done_dom_count())
        else:
            outstr += "WARNING: version mismatch\n"
            for version in vcnt:
                outstr += "%2d DOMs with %s: " % (vcnt[version], version)
                for dom in list(self.dom_dict.keys()):
                    if self.get_version(dom) == version:
                        outstr += "%s " % dom
                outstr += "\n"
        return outstr


class ThreadSet(object):
    """
    Lightweight class to handle concurrent ThreadableProcesses
    """
    def __init__(self, verbose=False):
        self.hubs = []
        self.procs = {}
        self.threads = {}
        self.output = {}
        self.verbose = verbose

    def add(self, cmd, hub=None):
        if not hub:
            hub = len(self.hubs)
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
    def __init__(self, verbose=False, watch_period=15, straggler_time=240):
        ThreadSet.__init__(self, verbose)
        self.watch_period = watch_period
        self.straggler_time = straggler_time

    def summary(self):
        sumstr = ""
        failed_doms = 0
        warning_doms = 0
        done_doms = 0
        for hub in self.hubs:
            cntr = DOMCounter(self.procs[hub].results())
            dom_count = len(cntr.doms())
            done = cntr.done_dom_count()
            done_doms += done
            warning_doms += len(cntr.warning_doms())
            # Include DOMs which didn't complete
            failed_doms += (dom_count - done)
            sumstr += "%s: %s\n" % (hub, str(cntr).strip())
        sumstr += "%d DOMs uploaded successfully" % done_doms
        sumstr += " (%d with warnings)\n" % warning_doms
        sumstr += "%d DOMs did not upload successfully\n" % failed_doms
        return sumstr

    def watch(self):
        tstart = datetime.datetime.now()
        while True:
            now = datetime.datetime.now()
            delta = now - tstart
            if delta.seconds > 0 and delta.seconds % self.watch_period == 0:
                num_done = 0
                done_dom_count = 0
                for hub in self.hubs:
                    cntr = DOMCounter(self.procs[hub].results())
                    done_dom_count += cntr.done_dom_count()
                    if self.procs[hub].done:
                        num_done += 1
                    not_doms = cntr.not_done_doms()
                    if not_doms and delta.seconds > self.straggler_time:
                        print("Waiting for %s:" % hub)
                        for not_done in cntr.not_done_doms():
                            print("\t%s: %s" %
                                  (not_done.cwd, not_done.last_state()))
                if num_done == len(self.hubs):
                    break
                print("%s Done with %d of %d hubs (%d DOMs)." %
                      (datetime.datetime.now(), num_done, len(self.hubs),
                       done_dom_count))
            time.sleep(1)


def test_procs():
    thrds = HubThreadSet(verbose=True)
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
        thrds.add("./simUpload.py", hub)
    thrds.start()
    try:
        thrds.watch()
    except KeyboardInterrupt:
        thrds.stop()


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config-name", dest="clu_cfg_name",
                        help=("Cluster configuration name, subset of deployed"
                              " configuration."))
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Be chatty")
    parser.add_argument("-f", "--skip-flash", dest="skip_flash",
                        action="store_true", default=False,
                        help=("Don't actually write flash on DOMs -"
                              " just 'practice' all other steps"))
    parser.add_argument("-s", "--straggler-time", type=int,
                        dest="straggler_time",
                        default=240,
                        help=("Time (seconds) to wait before reporting details"
                              " of straggler DOMs (default: 240)"))
    parser.add_argument("-w", "--watch-period", type=int, dest="watch_period",
                        default=15,
                        help=("Interval (seconds) between status reports"
                              " during upload (default: 15)"))
    parser.add_argument("-z", "--no-schema-validation", dest="validation",
                        action="store_false", default=True,
                        help=("Disable schema validation of xml configuration"
                              " files"))
    parser.add_argument("release_file")

    args = parser.parse_args()

    release_file = args.release_file

    # Make sure file exists
    if not os.path.exists(release_file):
        print("Release file %s doesn't exist!\n\n" % release_file)
        raise SystemExit

    try:
        cluster_config = \
            DAQConfigParser.get_cluster_configuration(args.clu_cfg_name,
                                                      validate=args.validation)
    except DAQConfigException as exc:
        print('Cluster configuration file problem:\n%s' % exc, file=sys.stderr)
        raise SystemExit

    hublist = cluster_config.get_hub_nodes()

    # Copy phase - copy mainboard release.hex file to remote nodes
    copy_set = ThreadSet(args.verbose)

    remote_file = "/tmp/release%d.hex" % os.getpid()
    for domhub in hublist:
        copy_set.add("scp -q %s %s:%s" % (release_file, domhub, remote_file))

    print("Copying %s to all hubs as %s..." % (release_file, remote_file))
    copy_set.start()
    try:
        copy_set.wait()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        copy_set.stop()
        raise SystemExit

    # Upload phase - upload release
    print("Uploading %s on all hubs..." % remote_file)

    uploader = HubThreadSet(args.verbose, args.watch_period,
                            args.straggler_time)
    for domhub in hublist:
        flg = "-f" if args.skip_flash else ""
        cmd = "ssh %s UploadDOMs.py %s -v %s" % (domhub, remote_file, flg)
        uploader.add(cmd, domhub)

    uploader.start()
    try:
        uploader.watch()
    except KeyboardInterrupt:
        print("Got keyboardInterrupt... stopping threads...")
        uploader.stop()
        try:
            uploader.wait()
            print("Killing remote upload processes...")
            killer = ThreadSet(args.verbose)
            for domhub in hublist:
                killer.add("ssh %s killall -9 UploadDOMs.py" % domhub, domhub)
            killer.start()
            killer.wait()
        except KeyboardInterrupt:
            pass

    # Cleanup phase - remove remote files from /tmp on hubs
    cleanup_set = ThreadSet(args.verbose)
    for domhub in hublist:
        cleanup_set.add("ssh %s /bin/rm -f %s" % (domhub, remote_file))

    print("Cleaning up %s on all hubs..." % remote_file)
    cleanup_set.start()
    try:
        cleanup_set.wait()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        cleanup_set.stop()
        raise SystemExit

    print("\n\nDONE.")
    print(uploader.summary())


if __name__ == "__main__":
    main()
