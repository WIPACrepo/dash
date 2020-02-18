#!/usr/bin/env python
#
# Check the pDAQ/config directory on expcont for files which have been
# used in data-taking but have not been committed

from __future__ import print_function

import os
import re
import smtplib
import subprocess
import sys
import time


from DAQConfig import DAQConfigParser
from decorators import classproperty
from locate_pdaq import find_pdaq_config
from utils.Machineid import Machineid


class Ancient(object):
    """
    Object representing an "ancient" file (older than one year)
    """

    def __init__(self, filename, mtime):
        self.__filename = filename
        self.__mtime = mtime

    def __cmp__(self, other):
        return self.mtime - other.mtime

    def __str__(self):
        return "%s (%d days)" % \
            (self.__filename, self.__mtime / (60 * 60 * 24))

    @property
    def mtime(self):
        "Return the modification time for this file"
        return self.__mtime


class ConfigDirChecker(object):
    """
    Check pDAQ config directory for unadded/uncommitted files
    """
    INDENT = "    "

    # cached list of shell PATH elements
    PATH_LIST = None

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

        self.__path = None
        self.__mysql_bin = None
        self.__svn_bin = None

        self.__processlist = []

        self.__added = []
        self.__modified = []
        self.__unknown = []
        self.__ancient = []

    def __add_missing_to_svn(self, dryrun=False):
        """
        'svn add' uncommitted files
        """
        for fnm in self.__processlist:
            rtnval = self.__svn_add(self.__cfgdir, fnm, dryrun=dryrun)
            if rtnval:
                self.__added.append(fnm)

    def __check_used_configs(self, used, svnmap):
        """
        Check that all used configuration files (and included files)
        have been added to the SVN repository
        """
        for name in used:
            if name.endswith(".xml"):
                full = name
            else:
                full = name + ".xml"
            self.__check_svn_status(full, svnmap)

        # if we found run configuration files to be added...
        if len(self.__processlist) > 0:  # pylint: disable=len-as-condition
            for fnm in self.__processlist[:]:
                # load run configuration file
                print("!!! Loading %s" % fnm)
                try:
                    cfg = DAQConfigParser.parse(self.__cfgdir, fnm,
                                                strict=False)
                except:  # pylint: disable=bare-except
                    import traceback
                    print("!!! Ignoring bad %s" % fnm, file=sys.stderr)
                    traceback.print_exc()
                    continue

                # check that all dom config files have been added
                for domcfg in cfg.dom_configs:
                    full = os.path.join("domconfigs", domcfg.filename)
                    self.__check_svn_status(full, svnmap)

                # check that trigger config file has been added
                full = os.path.join("trigger", cfg.trigger_config.filename)
                self.__check_svn_status(full, svnmap)

        # add remaining uncommitted files to the list of unknown files
        for key in svnmap:
            if svnmap[key] != "?":
                continue

            full = os.path.join(self.__cfgdir, key)

            # ignore directories
            if not os.path.isdir(full):
                self.__unknown.append(key)

    def __check_svn_status(self, path, svnmap):
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
                print("Not handling SVN status type %s for %s" %
                      (svnmap[path], path), file=sys.stderr)

    def __send_email(self, dryrun=False):
        intro = ("Subject: Modified run configuration(s) on SPS\n\n" +
                 "Hello daq-dev,\n")

        if len(self.__modified) == 0:  # pylint: disable=len-as-condition
            modstr = ""
        else:
            modstr = "There are modified run configuration files in" \
                     " access:~pdaq/config on SPS.\nPlease check in valid" \
                     " changes and/or revert modified files.\n\n\t" + \
                     "\n\t".join(self.__modified)

        if len(self.__ancient) == 0:  # pylint: disable=len-as-condition
            oldstr = ""
        else:
            self.__ancient.sort()
            oldstr = "There are run configuration files more than one year" \
                     " old.\nThey should probably be removed.\n\n\t" + \
                     "\n\t".join(str(x) for x in self.__ancient)

        if modstr != "" and oldstr != "":
            middle = "\n\n\n"
        else:
            middle = ""

        fromaddr = "pdaq@icecube.usap.gov"
        toaddr = "daq-dev@icecube.wisc.edu"
        body = intro + modstr + middle + oldstr

        if dryrun:
            print("From: " + fromaddr)
            print("To: " + toaddr)
            print(body)
            return

        session = smtplib.SMTP("mail.southpole.usap.gov")
        session.sendmail(fromaddr, (toaddr, ), body)
        session.quit()

    def __find_ancient_unknown(self):
        now = time.time()
        one_year_ago = now - 60 * 60 * 24 * 365

        viable = []
        for fnm in self.__unknown:
            if fnm.find("/") >= 0 or not fnm.endswith(".xml"):
                continue

            stat = os.stat(os.path.join(self.__cfgdir, fnm))
            if stat.st_mtime < one_year_ago:
                self.__ancient.append(Ancient(fnm, stat.st_mtime))
            else:
                viable.append(fnm)

        if len(viable) < len(self.__unknown):
            self.__unknown = viable

    def __get_directory_svn_status(self, dirname):
        """
        Get the SVN status for all files in the current directory
        """
        proc = subprocess.Popen((self.svn_bin, "status"),
                                stdout=subprocess.PIPE, cwd=dirname)

        pat = re.compile(r"^(.)\s+(.*)$")

        svnmap = {}
        for line in proc.stdout:
            line = line.rstrip()

            mtch = pat.match(line)
            if mtch is not None:
                svnmap[mtch.group(2)] = mtch.group(1)
                continue

            print("Bad SVN line in %s: \"%s\"" % (self.__cfgdir, line),
                  file=sys.stderr)

        proc.stdout.close()
        proc.wait()

        return svnmap

    def __get_used_configs(self, db_name):
        """
        Return a list of configurations which have been used in a run
        """
        # NOTE: query must end with a semicolon
        query = "select daq_label from run_summary group by daq_label;"

        cmd_args = (self.mysql_bin,
                    "-h", "dbs",
                    "-u", "i3omdbro",
                    "-D", db_name,
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

        if len(configs) == 0:  # pylint: disable=len-as-condition
            raise Exception("Couldn't find any configuration names in" +
                            " the database")

        return configs

    def __report(self, verbose=False, show_unknown=False):
        """
        Report the results

        verbose - if False, print a one-line summary
                  if True, print the names of added, modified, and
                           unknown files
        show_unknown - if True, don't report unknown files
        """
        need_spaces = False

        if not verbose:
            outstr = ""
            for pair in ((len(self.__added), "added"),
                         (len(self.__modified), "modified"),
                         (len(self.__unknown), "unknown")):
                if pair[0] > 0:
                    if outstr != "":
                        outstr += ", "
                    outstr += "%d %s" % pair
            if outstr != "":
                print(outstr)
            return

        if len(self.__added) > 0:  # pylint: disable=len-as-condition
            print("Added %d configuration files:" % len(self.__added))
            for fnm in self.__added:
                print(self.INDENT + fnm)
            need_spaces = True

        if len(self.__modified) > 0:  # pylint: disable=len-as-condition
            if need_spaces:
                print()
                print()
            print("Found %d modified configuration files:" %
                  len(self.__modified))
            for fnm in self.__modified:
                print(self.INDENT + fnm)
            need_spaces = True

        if show_unknown and \
          len(self.__unknown) > 0:  # pylint: disable=len-as-condition
            if need_spaces:
                print()
                print()
            print("Found %d unknown configuration files:" %
                  len(self.__unknown))
            for fnm in self.__unknown:
                print(self.INDENT + fnm)
            need_spaces = True

    def __svn_add(self, svndir, name, dryrun=False):
        """
        Add a file to the local SVN repository
        """
        if dryrun:
            print("%s add %s" % (self.svn_bin, name))
            return True

        proc = subprocess.Popen((self.svn_bin, "add", name),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                cwd=svndir)

        outlines = proc.stdout
        proc.stdout.close()
        proc.wait()
        if proc.returncode != 0:
            print("Failed to SVN ADD %s:" % name, file=sys.stderr)
            for line in outlines:
                print(self.INDENT + line, file=sys.stderr)

        return proc.returncode == 0

    def __svn_commit(self, svndir, commit_msg, filelist, dryrun=False):
        """
        Commit all added/modified files to the master SVN repository
        """
        if dryrun:
            print("%s commit -m\"%s\" %s" %
                  (self.svn_bin, commit_msg, " ".join(filelist)))
            return True

        proc = subprocess.Popen([self.svn_bin, "commit", "-m",
                                 commit_msg] + filelist,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                cwd=svndir)

        outlines = proc.stdout
        proc.stdout.close()
        proc.wait()
        if proc.returncode != 0:
            print("Failed to SVN COMMIT %s:" % " ".join(filelist),
                  file=sys.stderr)
            for line in outlines:
                print(self.INDENT + line, file=sys.stderr)

        return proc.returncode == 0

    @classmethod
    def find_executable(cls, cmd, helptext=None, dryrun=False):
        "Find 'cmd' in the user's PATH"
        for pdir in cls.path_elements:
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

    @property
    def mysql_bin(self):
        "Return the full path for the MySQL executable"
        if self.__mysql_bin is None:
            self.__mysql_bin = self.find_executable("mysql")
        return self.__mysql_bin

    @classproperty
    def path_elements(cls):  # pylint: disable=no-self-argument
        "Yield each entry in the user's $PATH environment variable"

        if cls.PATH_LIST is None:
            cls.PATH_LIST = os.environ["PATH"].split(":")
        for elem in cls.PATH_LIST:
            yield elem

    def run(self, db_name, dryrun=False, verbose=False, show_unknown=False,
            commit=False):
        """
        Check pDAQ config directory and report results
        """
        used = self.__get_used_configs(db_name)
        svnmap = self.__get_directory_svn_status(self.__cfgdir)
        self.__check_used_configs(used, svnmap)
        self.__add_missing_to_svn(dryrun)
        self.__find_ancient_unknown()
        if commit:
            # pylint: disable=len-as-condition
            if len(self.__added) > 0:
                self.__svn_commit(self.__cfgdir, "Check in uncommitted" +
                                  " run configuration files", self.__added,
                                  dryrun=dryrun)
            if len(self.__modified) > 0 or len(self.__ancient) > 0:
                self.__send_email(dryrun=dryrun)
        else:
            self.__report(verbose=verbose, show_unknown=show_unknown)

    @property
    def svn_bin(self):
        "Return the full path for the Subversion executable"
        if self.__svn_bin is None:
            self.__svn_bin = self.find_executable("svn")
        return self.__svn_bin


def main():
    "Main program"
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--commit", dest="commit",
                        action="store_true", default=False,
                        help="Commit changes to SVN repo in the North")
    parser.add_argument("-d", "--config-dir", dest="configdir",
                        help=("Location of configuration directory"
                              " being checked"))
    parser.add_argument("-D", "--dbname", dest="db_name",
                        default="I3OmDb",
                        help="Name of database to check")
    parser.add_argument("-n", "--dry-run", dest="dryrun",
                        action="store_true", default=False,
                        help="Don't add files to SVN")
    parser.add_argument("-u", "--show-unknown", dest="show_unknown",
                        action="store_true", default=False,
                        help=("Print list of all unknown files found"
                              " in $PDAQ_CONFIG"))
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print details of operation")
    args = parser.parse_args()

    hostid = Machineid()
    if not hostid.is_sps_cluster:
        raise SystemExit("This script should only be run on SPS")

    chk = ConfigDirChecker(args.configdir)
    chk.run(args.db_name, dryrun=args.dryrun, verbose=args.verbose,
            show_unknown=args.show_unknown, commit=args.commit)


if __name__ == "__main__":
    main()
