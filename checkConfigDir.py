#!/usr/bin/env python
#
# Check the pDAQ/config directory on expcont for files which have been
# used in data-taking but have not been committed

import os
import re
import subprocess
import sys


from DAQConfig import DAQConfigParser
from locate_pdaq import find_pdaq_config


class ConfigDirChecker(object):
    """
    Check pDAQ config directory for unadded/uncommitted files
    """
    INDENT = "    "

    MYSQL_BIN = "/usr/bin/mysql"

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

        if not os.path.exists(self.MYSQL_BIN):
            raise Exception("MySQL executable \"%s\" does not exist" %
                            self.MYSQL_BIN)

        self.__processlist = []

        self.__added = []
        self.__modified = []
        self.__unknown = []

    def __addMissingToSVN(self, dryrun=False):
        """
        'svn add' uncommitted files
        """
        for f in self.__processlist:
            if dryrun:
                print "Not adding %s" % f
                rtnval = True
            else:
                rtnval = self.__svn_add(self.__cfgdir, f)
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
                cfg = DAQConfigParser.load(f, self.__cfgdir, False)

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

    def __getDirectorySVNStatus(self, dir):
        """
        Get the SVN status for all files in the current directory
        """
        proc = subprocess.Popen(("/usr/bin/svn", "status"),
                                stdout=subprocess.PIPE, cwd=dir)

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

    def __getUsedConfigs(self):
        """
        Return a list of configurations which have been used in a run
        """
        # NOTE: query must end with a semicolon
        query = "select daq_label from run_summary group by daq_label;"

        cmd_args = (self.MYSQL_BIN,
                    "-h", "dbs",
                    "-u", "pnf",
                    "-D", "I3OmDb",
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

    def __report(self, quiet=False, showUnknown=False):
        """
        Report the results

        quiet - if True, print a one-line summary
                if False, print the names of added, modified, and unknown files
        showUnknown - if True, don't report unknown files
        """
        needSpaces = False

        if quiet:
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

        if len(self.__unknown) > 0:
            if needSpaces:
                print
                print
            print "Found %d unknown configuration files:" % len(self.__unknown)
            for f in self.__unknown:
                print self.INDENT + f
            needSpaces = True

    def __svn_add(self, svndir, name):
        """
        Add a file to the local SVN repository
        """
        proc = subprocess.Popen(("/usr/bin/svn", "add", name),
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

    def run(self, dryrun=False, quiet=False, showUnknown=False):
        """
        Check pDAQ config directory and report results
        """
        used = self.__getUsedConfigs()
        svnmap = self.__getDirectorySVNStatus(self.__cfgdir)
        self.__checkUsedConfigs(used, svnmap)
        self.__addMissingToSVN(dryrun)
        self.__report(quiet=quiet, showUnknown=showUnknown)


if __name__ == "__main__":
    import optparse

    p = optparse.OptionParser()
    p.add_option("-d", "--config-dir", type="string", dest="configdir",
                 action="store", default=None,
                 help="Location of configuration directory being checked")
    p.add_option("-n", "--dry-run", dest="dryrun",
                 action="store_true", default=False,
                 help="Don't add files to SVN")
    p.add_option("-q", "--quiet", dest="quiet",
                 action="store_true", default=False,
                 help="Don't print final report")
    p.add_option("-u", "--show-unknown", dest="showUnknown",
                 action="store_true", default=False,
                 help="Show unknown configurations")
    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Print a log of all actions")
    opt, args = p.parse_args()

    chk = ConfigDirChecker(opt.configdir)
    chk.run(dryrun=opt.dryrun, quiet=opt.quiet, showUnknown=opt.showUnknown)
