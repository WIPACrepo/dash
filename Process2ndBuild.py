#!/usr/bin/env python

"""
Process2ndBuild.py
Jacobsen, back in the 2007's or so

This script is installed on 2ndbuild and run from cron.  It collects the
output of 2ndbuild as it appears on /mnt/data/pdaqlocal, tars them in
groups as they appear, makes hard links for I3Moni, SNDAQ and SPADE, and
puts the appropriate semaphores in place.
"""

from __future__ import print_function

import datetime
import logging
import os
import sys
import tarfile
import time
import traceback

import icetop_hdf5

from DefaultDomGeometry import DefaultDomGeometryReader
from Process import exclusive_process, ProcessException

MAX_FILES_PER_TARBALL = 50


class SuperSaver(object):
    START_PREFIX = "supersaver."
    STOP_PREFIX = "supersaved."

    STATE_PRESTART = 0
    STATE_IN_RUN = 1

    def __init__(self):
        self.__run_times = {}

        self.__run = None
        self.__start = None
        self.__stop = None
        self.__state = self.STATE_PRESTART

    def __str__(self):
        if self.__run is None and self.__start is None and self.__stop is None:
            stat_str = ""
        else:
            stat_str = "#%s,%s-%s," % (self.__run, self.__start, self.__stop)
        no_times = len(self.__run_times) == 0
        return "SuperSaver[%s%s]%s" % \
          (stat_str, self.state,
           "" if no_times else "+%d" % len(self.__run_times))

    def __add_time(self, run, mtime, idx):
        if run not in self.__run_times:
            self.__run_times[run] = [None, None]
        self.__run_times[run][idx] = mtime

    def check_file(self, fname, mtime=None):
        """
        If file starts with start/stop prefix,
        add the time to our run start/stop dictionary and return True
        """
        for idx, prefix in enumerate((self.START_PREFIX, self.STOP_PREFIX)):
            if fname.startswith(prefix):
                if mtime is None:
                    mtime = os.stat(fname).st_mtime
                self.__add_time(fname[len(prefix):], mtime, idx)
                return True

        # this file isn't a SuperSaver sentinal file
        return False

    def clear_group(self, mtime, verbose=False, dry_run=False):
        logging.debug("Clearing group from %s after time %s",
                      self, mtime)
        if self.__stop is None or mtime < self.__stop:
            # we found a file for this SuperSaver run!
            if self.__state == self.STATE_PRESTART:
                # we finished processing all files before the SuperSaver run
                self.__state = self.STATE_IN_RUN
            logging.debug("Cleared group, now %s", self)
            return True

        # we've finished the current SuperSaver run, delete the sentinal files
        if not dry_run:
            for prefix in (self.START_PREFIX, self.STOP_PREFIX):
                fname = prefix + str(self.__run)
                try:
                    logging.error("Removing sentinal %s", fname)
                    os.remove(fname)
                    if verbose:
                        print("Deleted sentinal file %s" % fname)
                except OSError as err:
                    logging.error("Could not delete sentinal file %s: %s",
                                  fname, err)

        # return True if we have a start time for another SuperSaver run
        return self.find_first_time()

    def find_first_time(self, dry_run=False):
        # sort list by start time
        for run, times in sorted(list(self.__run_times.items()),
                                 key=lambda x: x[1][0]):
            # check for 'supersaver' stop times with no matching start time
            if times[0] is None and times[1] is not None:
                if not dry_run:
                    try:
                        os.remove(self.STOP_PREFIX + run)
                        logging.warning("Deleted orphaned SuperSaver stop file"
                                        " from run %s", run)
                    except OSError as err:
                        logging.error("Could not delete orphaned SuperSaver"
                                      " stop file from run %s: %s", run, err)
                continue

            # stash first run times
            self.__run = run
            self.__start = times[0]
            self.__stop = times[1]
            del self.__run_times[run]
            logging.debug("New group for %s", self)
            return True

        # no times found
        logging.debug("No groups found for %s", self)
        return False

    def found_group_end(self, mtime):
        logging.debug("Find SuperSaver group end using time %s"
                      " (run %s start %s stop %s state %s)", mtime,
                      self.__run, self.__start, self.__stop, self.state)
        if self.__state == self.STATE_PRESTART:
            if mtime < self.__start:
                # continue processing files preceeding the SuperSaver run
                logging.debug("*** PreStart -> False")
                return False

            self.__state = self.STATE_IN_RUN
            logging.debug("*** FoundRun -> True")
            return True

        if self.__state == self.STATE_IN_RUN:
            if self.__stop is None or mtime <= self.__stop:
                # continue processing SuperSaver files
                logging.debug("*** InRun -> False")
                return False

            logging.debug("*** PastRun -> True")
            return True

        raise Exception("Unknown state %s (type %s)" %
                        (self.__state, type(self.__state)))

    def in_range(self, mtime):
        return mtime >= self.__start and \
          (self.__stop is None or mtime <= self.__stop)

    @property
    def state(self):
        if self.__state == self.STATE_PRESTART:
            return "<prestart>"
        if self.__state == self.STATE_IN_RUN:
            return "<in_run>"
        return "<??%s??>" % str(self.__state)


def init_logging(log_level):
    """
    Write log messages to "process2nd.log", using the (optional) level
    specified in the 'log_level' string.
    Throw Exception if 'log_level' is not a valid logging level
    """
    default_level = logging.WARNING

    # convert the logging level string into a 'logging' attribute
    if log_level is None:
        py_level = default_level
    else:
        py_level = getattr(logging, log_level.upper(), None)
        if py_level is None:
            raise Exception("Invalid log level \"%s\"" % str(log_level))

    # configure logging
    logging.basicConfig(filename="process2nd.log", level=py_level)


def is_target_file(filename):
    "Does this file start with 'moni', 'sn', or 'tcal'?"
    if filename is None:
        return False

    return filename.startswith("moni_") or filename.startswith("sn_") or \
        filename.startswith("tcal_")


def process_files(spade_dir, create_icetop_hdf5=False, dry_run=False,
                  enable_moni_link=False, log_level=None, verbose=False):

    os.chdir(spade_dir)

    init_logging(log_level)

    # Get list of available files matching target tar pattern,
    # along with their modification times
    filedict = {}
    supersaver = SuperSaver()
    for fname in os.listdir(spade_dir):
        if is_target_file(fname):
            filedict[fname] = os.stat(fname).st_mtime
        else:
            # check for SuperSaver start/stop sentinal files
            supersaver.check_file(fname)

    if not supersaver.find_first_time():
        supersaver = None
    else:
        logging.debug("Found supersaver %s", str(supersaver))

    # Make list for tarball - restrict total number of files
    files_to_tar = []
    files_to_remove = []
    moni_files = []
    for name, mtime in sorted(list(filedict.items()), key=lambda x: x[1]):
        logging.debug("Checking file %s(%s)", name, mtime)
        if supersaver is not None:
            if supersaver.found_group_end(mtime):
                # if we're in a new group and the new time is outside the
                # current range, we must have *just* finished a set of
                # SuperSaver files
                do_extra_link = not supersaver.in_range(mtime)
                logging.debug("New group for %s (%sSuperSaver)",
                              name, "" if do_extra_link else "!")

                # process this group of files
                if len(files_to_tar) > 0:  # pylint: disable=len-as-condition
                    create_tar_and_sem_files(files_to_tar, verbose=verbose,
                                             dry_run=dry_run,
                                             enable_moni_link=enable_moni_link,
                                             is_supersaver=do_extra_link)

                # wait a second so the next file has a unique name
                time.sleep(1)

                # remember the processed files
                files_to_remove += files_to_tar

                # clear the list of files to process
                del files_to_tar[:]

                if not supersaver.clear_group(mtime, verbose=verbose,
                                              dry_run=dry_run):
                    logging.debug("Finished SuperSaver data before %s(%s)",
                                  name, mtime)
                    supersaver = None

        files_to_tar.append(name)
        if create_icetop_hdf5 and name.startswith("moni_"):
            moni_files.append(name)
        if len(files_to_tar) >= MAX_FILES_PER_TARBALL:
            logging.debug("Found maximum %d files for current tarball",
                          len(files_to_tar))
            break

    if len(files_to_tar) != 0:  # pylint: disable=len-as-condition
        do_extra_link = supersaver is not None

        create_tar_and_sem_files(files_to_tar, verbose=verbose,
                                 dry_run=dry_run,
                                 enable_moni_link=enable_moni_link,
                                 is_supersaver=do_extra_link)

    if create_icetop_hdf5 and \
      len(moni_files) > 0:  # pylint: disable=len-as-condition
        # read in default-dom-geometry.xml
        ddg = DefaultDomGeometryReader.parse(translate_doms=True)

        # cache the DOM ID -> DOM dictionary
        dom_dict = ddg.get_dom_id_to_dom_dict()

        icetop_hdf5.process_list(moni_files, dom_dict, verbose=verbose,
                                 dry_run=dry_run)

    # Clean up tar'ed files
    for fname in files_to_tar + files_to_remove:
        if verbose:
            print("Removing %s..." % (fname, ))
        if not dry_run:
            os.unlink(fname)

    return True


def create_tar_and_sem_files(files_to_tar, verbose=False, dry_run=False,
                             enable_moni_link=False, is_supersaver=False):
    if verbose:
        print("Found %d files" % len(files_to_tar))

    now = datetime.datetime.now()
    date_tag = "%03d_%04d%02d%02d_%02d%02d%02d_%06d" % \
        (0, now.year, now.month, now.day, now.hour, now.minute, now.second, 0)
    front = "SPS-pDAQ-2ndBld-" + date_tag
    spade_tar = front + ".dat.tar"
    spade_sem = front + ".sem"
    monilink = front + ".mon.tar"
    moni_sem = front + ".msem"
    snlink = front + ".sn.tar"
    savelink = front + ".save.tar"

    logging.debug("Writing %d files to %s", len(files_to_tar), front)

    # Duplicate file: wait for a new second, recalculate everything:
    if os.path.exists(spade_tar):
        time.sleep(1)
        return True

    # Create temporary tarball
    tmp_tar = "tmp-" + date_tag + ".tar"
    if verbose:
        print("Creating temporary tarball")
    try:
        if not dry_run:
            tarball = tarfile.open(tmp_tar, "w")
        for tfile in files_to_tar:
            if verbose:
                print("  %s" % str(tfile))
            logging.debug("++ %s", tfile)
            if not dry_run:
                tarball.add(tfile)
        if not dry_run:
            tarball.close()
    except:
        os.unlink(tmp_tar)
        raise
    if verbose:
        print("Done.")

    # Rename temporary tarball to SPADE name
    if verbose:
        print("Renaming temporary tarball to %s" % spade_tar)
    if not dry_run:
        os.rename(tmp_tar, spade_tar)

    # Create moni hard link
    if enable_moni_link:
        if verbose:
            print("MoniLink %s" % monilink)
        if not dry_run:
            os.link(spade_tar, monilink)

    # Create sn hard link
    if verbose:
        print("SNLink %s" % snlink)
    if not dry_run:
        os.link(spade_tar, snlink)
        # So that SN process can delete if it's not running as pdaq
        os.chmod(snlink, 0o666)

    # Create SuperSaver link, if requested
    if is_supersaver:
        os.link(spade_tar, savelink)

    # Create spade .sem
    if not dry_run:
        sem = open(spade_sem, "w")
        sem.close()

    # Create monitoring .msem
    if enable_moni_link and not dry_run:
        sem = open(moni_sem, "w")
        sem.close()

    return False


def main():
    "Main program"

    # pylint: disable=invalid-name,wrong-import-position
    import argparse

    from ClusterDescription import ClusterDescription

    parser = argparse.ArgumentParser()
    parser.add_argument("-5", "--icetop-hdf5", dest="create_icetop_hdf5",
                        action="store_false", default=True,
                        help="Do NOT create HDF5 files for IceTop")
    parser.add_argument("-d", "--spadedir", dest="spadedir",
                        action="store", default=None,
                        help="SPADE directory")
    parser.add_argument("-l", "--log-level", dest="log_level",
                        action="store", default=None,
                        help=("Logging level (DEBUG, INFO, WARNING, ERROR,"
                              " CRITICAL)"))
    parser.add_argument("-m", "--enable-moni-link", dest="enable_moni_link",
                        action="store_true", default=False,
                        help="Include moni files and create a moni link")
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help="Do not actually do anything")
    parser.add_argument("-q", "--quiet", dest="verbose",
                        action="store_false", default=False,
                        help="Do not print log of actions to console")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print log of actions to console (default)")

    args = parser.parse_args()

    if args.spadedir is not None:
        spade_dir = args.spadedir
    else:
        cluster = ClusterDescription()
        spade_dir = cluster.log_dir_for_spade

    # use '.pid' file to ensure multiple instances aren't
    # adding the same files to different tar files
    guard_file = os.path.join(os.environ["HOME"], ".proc2ndbld.pid")
    try:
        with exclusive_process(guard_file):
            process_files(spade_dir,
                          create_icetop_hdf5=args.create_icetop_hdf5,
                          dry_run=args.dry_run,
                          enable_moni_link=args.enable_moni_link,
                          log_level=args.log_level, verbose=args.verbose)
    except ProcessException:
        if sys.stdout.isatty():
            traceback.print_exc()


if __name__ == "__main__":
    main()
