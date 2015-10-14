#!/usr/bin/env python
#
# Check the pDAQ/config directory on expcont for files which have been
# used in data-taking but have not been committed

import os
import re
import smtplib
import subprocess
import sys
import time


from DAQConfig import DAQConfigParser
from locate_pdaq import find_pdaq_config
from utils.Machineid import Machineid


class Ancient(object):
    def __init__(self, filename, mtime):
        self.__filename = filename
        self.__mtime = mtime

    def __cmp__(self, other):
        return self.__mtime - other.__mtime

    def __str__(self):
        return "%s (%d days)" % \
            (self.__filename, self.__mtime / (60 * 60 * 24))


class ConfigDirChecker(object):
    """
    Check pDAQ config directory for unadded/uncommitted files
    """
    INDENT = "    "

    PATH = None
    MYSQL_BIN = None
    SVN_BIN = None

    def __init__(self, cfgdir=None):
        """
        Create a config directory checker

        cfgdir - pDAQ configuration directory to check
        """
        if cfgdir is not None:
            self.__cfgdir = cfgdir
        else:
            self.__cfgdir = find_pdaq_config()
        if not os.path.isdir(self.__cfgdir):
            raise Exception("No current pDAQ directory \"%s\"" % self.__cfgdir)

        if self.MYSQL_BIN is None:
            self.MYSQL_BIN = self.find_executable("mysql")
        if self.SVN_BIN is None:
            self.SVN_BIN = self.find_executable("svn")

        self.__processlist = []

        self.__added = []
        self.__modified = []
        self.__unknown = []
        self.__ancient = []

    def __addMissingToSVN(self, dryrun=False):
        """
        'svn add' uncommitted files
        """
        for f in self.__processlist:
            rtnval = self.__svn_add(self.__cfgdir, f, dryrun=dryrun)
            if rtnval:
                self.__added.append(f)

    def __checkUsedConfigs(self, used, svnmap):
        """
        Check that all used configuration files (and included files)
        have been added to the SVN repository
        """
        for u in used:
            if u.endswith(".xml"):
                full = u
            else:
                full = u + ".xml"
            self.__checkSVNStatus(full, svnmap)

        # if we found run configuration files to be added...
        if len(self.__processlist) > 0:
            for f in self.__processlist[:]:
                # load run configuration file
                print "!!! Loading %s" % f
                cfg = DAQConfigParser.parse(False, f, self.__cfgdir)

                # check that all dom config files have been added
                for dc in cfg.getDomConfigs():
                    full = os.path.join("domconfigs", dc.filename)
                    self.__checkSVNStatus(full, svnmap)

                # check that trigger config file has been added
                full = os.path.join("trigger",
                                    cfg.getTriggerConfig().filename)
                self.__checkSVNStatus(full, svnmap)

        # add remaining uncommitted files to the list of unknown files
        for key in svnmap:
            if svnmap[key] != "?":
                continue

            full = os.path.join(self.__cfgdir, key)

            # ignore directories
            if not os.path.isdir(full):
                self.__unknown.append(key)

    def __checkSVNStatus(self, path, svnmap):
        """
        Check the SVN status for 'path'
        """
        if path in svnmap:
            if svnmap[path] == "?":
                # 'svn add' unknown files
                self.__processlist.append(path)
                del svnmap[path]
            elif svnmap[path] == "M":
                # warn about modified files
                self.__modified.append(path)
                del svnmap[path]
            elif svnmap[path] == "A":
                # remember previously added files
                self.__added.append(path)
                del svnmap[path]
            else:
                # complain about all others
                print >>sys.stderr, \
                    "Not handling SVN status type %s for %s" % \
                    (svnmap[path], path)

    def __send_email(self, dryrun=False):
        intro = ("Subject: Modified run configuration(s) on SPS\n\n" +
                 "Hello daq-dev,\n")

        if len(self.__modified) == 0:
            modstr = ""
        else:
            modstr = \
                ("There are modified run configuration files in" +
                 " access:~pdaq/config on SPS.\nPlease check in valid changes" +
                 " and/or revert modified files.\n\n\t" +
                 "\n\t".join(self.__modified))

        if len(self.__ancient) == 0:
            oldstr = ""
        else:
            self.__ancient.sort()
            oldstr = \
                ("There are run configuration files more than one year old.\n" +
                 "They should probably be removed.\n\n\t" +
                 "\n\t".join(str(x) for x in self.__ancient))

        if modstr != "" and oldstr != "":
            middle = "\n\n\n"
        else:
            middle = ""

        fromaddr = "pdaq@icecube.usap.gov"
        toaddr = "daq-dev@icecube.wisc.edu"
        body = intro + modstr + middle + oldstr

        if dryrun:
            print "From: " + fromaddr
            print "To: " + toaddr
            print body
            return

        s = smtplib.SMTP("mail.southpole.usap.gov")
        s.sendmail(fromaddr, (toaddr, ), body)
        s.quit()

    def __findAncientUnknown(self):
        now = time.time()
        oneYearAgo = now - 60 * 60 * 24 * 365

        viable = []
        for f in self.__unknown:
            if f.find("/") >= 0 or not f.endswith(".xml"):
                continue

            st = os.stat(os.path.join(self.__cfgdir, f))
            if st.st_mtime < oneYearAgo:
                self.__ancient.append(Ancient(f, st.st_mtime))
            else:
                viable.append(f)

        if len(viable) < len(self.__unknown):
            self.__unknown = viable

    @classmethod
    def find_executable(cls, cmd, helptext=None, dryrun=False):
        "Find 'cmd' in the user's PATH"
        if cls.PATH is None:
            cls.PATH = os.environ["PATH"].split(":")
        for pdir in cls.PATH:
            pcmd = os.path.join(pdir, cmd)
            if os.path.exists(pcmd):
                return pcmd
        if dryrun:
            return cmd

        if helptext is None:
            helptext = ""
        else:
            helptext = "; %s" % helptext

        raise SystemExit("'%s' does not exist%s" % (cmd, helptext))

    def __getDirectorySVNStatus(self, dirname):
        """
        Get the SVN status for all files in the current directory
        """
        proc = subprocess.Popen((self.SVN_BIN, "status"),
                                stdout=subprocess.PIPE, cwd=dirname)

        pat = re.compile(r"^(.)\s+(.*)$")

        svnmap = {}
        for line in proc.stdout:
            line = line.rstrip()

            m = pat.match(line)
            if not m:
                print >>sys.stderr, "Bad SVN line in %s: \"%s\"" % \
                    (self.__cfgdir, line)
                continue

            svnmap[m.group(2)] = m.group(1)

        proc.stdout.close()
        proc.wait()

        return svnmap

    def __getUsedConfigs(self, dbName):
        """
        Return a list of configurations which have been used in a run
        """
        # NOTE: query must end with a semicolon
        query = "select daq_label from run_summary group by daq_label;"

        cmd_args = (self.MYSQL_BIN,
                    "-h", "dbs",
                    "-u", "i3omdbro",
                    "-D", dbName,
                    "-e", query)

        proc = subprocess.Popen(cmd_args, stdout=subprocess.PIPE)

        # add all known run configuration name to the 'config' list
        configs = []
        for line in proc.stdout:
            line = line.rstrip()
            if not line.endswith(".xml"):
                line += ".xml"
            configs.append(line)
        proc.stdout.close()
        proc.wait()

        if len(configs) == 0:
            raise Exception("Couldn't find any configuration names in" +
                            " the database")

        return configs

    def __report(self, verbose=False, showUnknown=False):
        """
        Report the results

        verbose - if False, print a one-line summary
                  if True, print the names of added, modified, and unknown files
        showUnknown - if True, don't report unknown files
        """
        needSpaces = False

        if not verbose:
            outstr = ""
            for pair in ((len(self.__added), "added"),
                         (len(self.__modified), "modified"),
                         (len(self.__unknown), "unknown")):
                if pair[0] > 0:
                    if len(outstr) > 0:
                        outstr += ", "
                    outstr += "%d %s" % pair
            if len(outstr) > 0:
                print outstr
            return

        if len(self.__added) > 0:
            print "Added %d configuration files:" % len(self.__added)
            for f in self.__added:
                print self.INDENT + f
            needSpaces = True

        if len(self.__modified) > 0:
            if needSpaces:
                print
                print
            print "Found %d modified configuration files:" % \
                len(self.__modified)
            for f in self.__modified:
                print self.INDENT + f
            needSpaces = True

        if showUnknown and len(self.__unknown) > 0:
            if needSpaces:
                print
                print
            print "Found %d unknown configuration files:" % len(self.__unknown)
            for f in self.__unknown:
                print self.INDENT + f
            needSpaces = True

    def __svn_add(self, svndir, name, dryrun=False):
        """
        Add a file to the local SVN repository
        """
        if dryrun:
            print "%s add %s" % (self.SVN_BIN, name)
            return True

        proc = subprocess.Popen((self.SVN_BIN, "add", name),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                cwd=svndir)

        outlines = proc.stdout
        proc.stdout.close()
        proc.wait()
        if proc.returncode != 0:
            print >>sys.stderr, "Failed to SVN ADD %s:" % name
            for line in outlines:
                print >>sys.stderr, self.INDENT + line

        return proc.returncode == 0

    def __svn_commit(self, svndir, commit_msg, filelist, dryrun=False):
        """
        Commit all added/modified files to the master SVN repository
        """
        if dryrun:
            print "%s commit -m\"%s\" %s" % \
                (self.SVN_BIN, commit_msg, " ".join(filelist))
            return True

        proc = subprocess.Popen([self.SVN_BIN, "commit", "-m",
                                 commit_msg] + filelist,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                cwd=svndir)

        outlines = proc.stdout
        proc.stdout.close()
        proc.wait()
        if proc.returncode != 0:
            print >>sys.stderr, "Failed to SVN COMMIT %s:" % " ".join(filelist)
            for line in outlines:
                print >>sys.stderr, self.INDENT + line

        return proc.returncode == 0

    def run(self, dbName, dryrun=False, verbose=False, showUnknown=False,
            commit=False):
        """
        Check pDAQ config directory and report results
        """
        used = self.__getUsedConfigs(dbName)
        svnmap = self.__getDirectorySVNStatus(self.__cfgdir)
        self.__checkUsedConfigs(used, svnmap)
        self.__addMissingToSVN(dryrun)
        self.__findAncientUnknown()
        if commit:
            if len(self.__added) > 0:
                self.__svn_commit(self.__cfgdir, "Check in uncommitted" +
                                  " run configuration files", self.__added,
                                  dryrun=dryrun)
            if len(self.__modified) > 0 or len(self.__ancient) > 0:
                self.__send_email(dryrun=dryrun)
        else:
            self.__report(verbose=verbose, showUnknown=showUnknown)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("-c", "--commit", dest="commit",
                   action="store_true", default=False,
                   help="Commit changes to SVN repo in the North")
    p.add_argument("-d", "--config-dir", dest="configdir",
                   help="Location of configuration directory being checked")
    p.add_argument("-D", "--dbname", dest="dbName",
                   default="I3OmDb",
                   help="Name of database to check")
    p.add_argument("-n", "--dry-run", dest="dryrun",
                   action="store_true", default=False,
                   help="Don't add files to SVN")
    p.add_argument("-u", "--show-unknown", dest="showUnknown",
                   action="store_true", default=False,
                   help="Print list of all unknown files found in $PDAQ_CONFIG")
    p.add_argument("-v", "--verbose", dest="verbose",
                   action="store_true", default=False,
                   help="Print details of operation")
    args = p.parse_args()

    hostid = Machineid()
    if not hostid.is_sps_cluster():
        raise SystemExit("This script should only be run on SPS")

    chk = ConfigDirChecker(args.configdir)
    chk.run(args.dbName, dryrun=args.dryrun, verbose=args.verbose,
            showUnknown=args.showUnknown, commit=args.commit)
