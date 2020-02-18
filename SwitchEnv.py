#!/usr/bin/env python

from __future__ import print_function

import logging
import os

from paramiko import AutoAddPolicy
from paramiko.client import SSHClient

from ClusterDescription import ClusterDescription
from utils.Machineid import Machineid


CHOICES = ["26", "27", "2.6", "2.7", "old", "OLD"]


def add_arguments(parser):
    "Add command-line arguments"
    parser.add_argument("-b", "--basename", dest="basename",
                        default="env",
                        help="Base file name (e.g. \"env\")")
    parser.add_argument("--choices", dest="print_choices",
                        action="store_true", default=False,
                        help="Print valid virtual environment names")
    parser.add_argument("-f", "--force", dest="force",
                        action="store_true", default=False,
                        help="Run this somewhere other than the SPTS cluster")
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help="Dry run (do not actually change anything)")
    parser.add_argument("virtualenv",
                        nargs="?", choices=CHOICES,
                        help="Virtual environment to use")


def update_virtualenv(args):
    if args.print_choices:
        for entry in CHOICES:
            print(entry)
        raise SystemExit

    # this script is meant to be run on spts-access
    mid = Machineid()
    if not mid.is_spts_cluster and not args.force:
        raise SystemExit("Add --force to run outside SPTS")
    if not mid.is_build_host and not args.force:
        raise SystemExit("Add --force to run on access")

    # get virtualenv directory name
    # NOTE: the directory version suffix is forced to upper case
    dotidx = args.virtualenv.find(".")
    if dotidx < 0:
        envname = args.basename + args.virtualenv.upper()
    else:
        envname = args.basename + args.virtualenv[:dotidx].upper() + \
          args.virtualenv[dotidx+1:].upper()

    # get the list of hosts from the cluster configuration file
    clucfg = ClusterDescription()
    for host in clucfg.hosts:
        print("Updating %s" % (host, ))
        venv = VirtualEnvironment(host)
        try:
            venv.update_symlink(args.basename, envname, dry_run=args.dry_run)
        finally:
            venv.close()

    cluname = ClusterDescription.get_cluster_name()
    print("Linked %s to %s on %s" % (args.basename, envname, cluname))


class ListEntry(object):
    "File/directory entry"
    def __init__(self, filename, is_dir=False):
        self.__name = filename
        self.__is_dir = is_dir

    def __str__(self):
        if self.__is_dir:
            slash = "/"
        else:
            slash = ""
        return self.__name + slash

    @property
    def filename(self):
        return self.__name

    @property
    def is_dir(self):
        "Is this a directory entry?"
        return self.__is_dir

    @property
    def is_link(self):
        "Is this a symlink entry?"
        return False


class ListSymlink(ListEntry):
    "Symbolic link entry"
    def __init__(self, filename):
        idx = filename.find(" -> ")
        if idx < 0:
            raise Exception("Found symlink without linked filename"
                            " (%s)" % (filename, ))
        super(ListSymlink, self).__init__(filename[:idx])

        self.__linked_to = filename[idx+4:]

    def __str__(self):
        return "%s -> %s" % (self.filename, self.__linked_to)

    @property
    def is_link(self):
        "Is this a symlink entry?"
        return True

    @property
    def linked_to(self):
        "Target location for this symlink"
        return self.__linked_to


class VirtualEnvironment(object):
    def __init__(self, host):
        self.__host = host

        self.__client = SSHClient()
        self.__client.load_system_host_keys()
        self.__client.set_missing_host_key_policy(AutoAddPolicy())

        self.__client.connect(self.__host)

    @classmethod
    def __parse_line(cls, line):
        "Parse a single line from 'ls'"
        (ftstr, nlinks, user, group, size, dstr1, dstr2, dstr3,
         fname) = line.split(None, 8)
        if ftstr == "":
            raise Exception("Found empty file type in \"%s\"" % (line, ))

        if ftstr[0] == "-":
            return ListEntry(fname)
        if ftstr[0] == "d":
            return ListEntry(fname, is_dir=True)
        if ftstr[0] == "l":
            return ListSymlink(fname)
        raise Exception("Unknown file type \"%s\" for \"%s\"" %
                        (ftstr[0], fname))

    def __rename_to_backup(self, file_dict, filename, dry_run=False,
                           max_backups=8):
        """
        Back up an existing file
        "foo" is renamed to "fooOLD" and any existing "fooOLD*" entries
        are incremented (e.g. "fooOLD3" is renamed to "fooOLD4")
        """

        # figure out how far back the revisions go
        newmax = max_backups
        for idx in range(0, max_backups):
            target = self.backup_name(filename, idx)
            if target not in file_dict:
                newmax = idx
                break

        # if we've reached the maximum number of backups, delete the oldest
        if newmax == max_backups:
            target = self.backup_name(filename, newmax)

        # move older backups (e.g. fooOLD2 becomes fooOLD3)
        new_name = None
        for idx in range(newmax, 0, -1):
            # generate file name(s)
            if new_name is None:
                new_name = self.backup_name(filename, idx)
            cur_name = self.backup_name(filename, idx - 1)

            # increment the "revision number" on this file/directory
            logging.info("Renaming \"%s:%s\" to \"%s\"", self.__host, cur_name,
                         new_name)
            cmd = "mv \"%s\" \"%s\"" % (cur_name, new_name)
            self.run_remote_no_output(cmd, dry_run=dry_run)

            # use 'new' name as next target
            new_name = cur_name

        # generate final name
        if new_name is None:
            new_name = self.backup_name(filename, 0)

        # finally back up the file they asked us to back up
        cmd = "mv \"%s\" \"%s\"" % (filename, new_name)
        self.run_remote_no_output(cmd, dry_run=dry_run)

    @classmethod
    def backup_name(cls, filename, backup_num):
        "Create a backup file name"
        if backup_num < 0:
            raise Exception("Backup number cannot be less than zero")

        if backup_num == 0:
            return "%sOLD" % filename

        return "%sOLD%d" % (filename, backup_num)

    def close(self):
        self.__client.close()
        self.__client = None

    def handle_existing_target(self, file_dict, srcdir, tgtdir, dry_run=False):
        """
        If the target exists and is a file/directory:
        * Rename it and return True
        If the target exists and is a symlink:
        * If it already points at the target, return False
        * Otherwise, remove the symlink and return True
        """
        # make sure the target directory exists
        tgtbase = os.path.basename(tgtdir)
        if tgtbase not in file_dict:
            logging.error("Target '%s' does not exist on host \"%s\"", tgtdir,
                          self.__host)
            return False

        # extract the name of the symlink to be created
        basename = os.path.basename(srcdir)

        # if the target name doesn't exist, we're done
        if basename not in file_dict:
            return True

        # if target is a directory...
        if file_dict[basename].is_dir:
            # rename directory so we can create a symlink
            self.__rename_to_backup(file_dict, basename, dry_run=dry_run)
            return True

        # if target is a symlink...
        if file_dict[basename].is_link:
            linkbase = os.path.basename(file_dict[basename].linked_to)
            if linkbase != tgtbase:
                # remove existing symlink
                cmd = "rm \"%s\"" % (srcdir, )
                self.run_remote_no_output(cmd, dry_run=dry_run)
                return True

            # target already points to the source directory
            if tgtdir == tgtbase:
                extra = ""
            else:
                extra = " (%s)" % (tgtdir, )
            print("\"%s\" already points to \"%s\"%s on %s" %
                  (srcdir, tgtbase, extra, self.__host))
            return False

        # if target isn't a directory or symlink, give up
        raise Exception("'%s' is not a directory or symlink!" % (srcdir, ))

    def list_entries(self, filespec):
        """
        Read 'ls' output from remote host and convert to dictionary of
        FileEntry objects
        """
        # assemble the list command
        cmd = "ls -ld %s" % (filespec, )

        # parse and save entries, cache errors until we exit the loop
        errstr = None
        not_found = False
        filedict = {}
        for is_stdout, line in self.run_remote(cmd):
            line = line.rstrip()
            if not is_stdout:
                # handle errors
                if line.find("No such file or directory") >= 0:
                    not_found = True
                else:
                    if errstr is None:
                        errstr = "'%s' errors from \"%s\":" % \
                          (cmd, self.__host, )
                    errstr += "\n" + line.rstrip()
                continue

            # parse list entry
            entry = self.__parse_line(line)

            # add new entry to the list
            basename = os.path.basename(entry.filename)
            filedict[basename] = entry

        # log any errors
        if not_found:
            logging.error("Cannot find \"%s\" on \"%s\"", filespec,
                          self.__host)
        if errstr is not None:
            logging.error(errstr)

        # return final dictionary of ListEntry objects from the host
        return filedict

    def run_remote(self, cmd, dry_run=False):
        """
        Run a command on the remote host.  Return output/error lines
        as a tuple (is_stdout, line) where 'is_stdout' is True if line is
        from standard output, False if from standard error.
        """
        if dry_run:
            print("%s: %s" % (self.__host, cmd, ))
            return

        stdin, stdout, stderr = self.__client.exec_command(cmd)

        # don't need to write to subprocess stdin
        stdin.close()

        # return individual output lines
        for line in stdout:
            yield True, line
        stdout.close()

        # return individual error lines
        for line in stderr:
            yield False, line
        stderr.close()

    def run_remote_no_output(self, cmd, dry_run=False):
        "Run a command on the remote host, logging any output as an error"
        errstr = None
        for line in self.run_remote(cmd, dry_run=dry_run):
            if errstr is None:
                errstr = "Unexpected '%s' output from \"%s\":" % \
                  (cmd, self.__host)
            errstr += "\n" + line.rstrip()
        if errstr is not None:
            logging.error(errstr)

    def update_symlink(self, srcdir, tgtdir, dry_run=False):
        "Update 'tgtdir' on remote host to point at 'srcdir'"
        # list entries which are variations of the source file
        file_dict = self.list_entries(srcdir + "*")
        if len(file_dict) == 0:  # pylint: disable=len-as-condition
            logging.info("No '%s' directories on \"%s\"", srcdir, self.__host)
            return

        # if target directory doesn't link to the requested target...
        if self.handle_existing_target(file_dict, srcdir, tgtdir):
            # link to new target
            cmd = "ln -s \"%s\" \"%s\"" % (tgtdir, srcdir)
            self.run_remote_no_output(cmd, dry_run=dry_run)


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    update_virtualenv(args)


if __name__ == "__main__":
    main()
