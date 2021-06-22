#!/usr/bin/env python

"""
SpadeQueue.py
John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
Started: Tue Aug 11 17:25:20 2009

Functions for putting SPADE data in queue, either 'by hand' (when
run from command line) or programmatically (when imported from, e.g.,
RunSet.py)

If run from 'cron', run as "SpadeQueue.py -a -c"
"""

from __future__ import print_function

import datetime
import errno
import os
import shutil
import subprocess
import tarfile

from ClusterDescription import ClusterDescription
from LogSorter import LogSorter
from utils.DashXMLLog import DashXMLLog, FileNotFoundException

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


# save the current run number
CURRENT_RUN_NUMBER = None

# name of file indicating that logs have been queued
FILE_MARKER = "logs-queued"

# 1 GB of log data is too large
TOO_LARGE = 1024 * 1024 * 1024 * 1.5

# name of combined log file
COMBINED_LOG = "combined.log"


def __copy_spade_tar_file(logger, copy_dir, spade_base_name, tar_file,
                          dry_run=False):
    copy_file = os.path.join(copy_dir, spade_base_name + ".dat.tar")
    if dry_run:
        print("ln %s %s" % (tar_file, copy_file))
        return

    logger.info("Link or copy %s->%s" % (tar_file, copy_file))
    try:
        os.link(tar_file, copy_file)
    except OSError as exc:
        if exc.errno == errno.EXDEV:  # Cross-device link
            shutil.copyfile(tar_file, copy_file)
        else:
            raise OSError(str(exc) + ": Copy %s to %s" % (tar_file, copy_file))


def __find_executable(cmd):
    """Find 'cmd' in the user's PATH"""
    path = os.environ["PATH"].split(":")
    for pdir in path:
        pcmd = os.path.join(pdir, cmd)
        if os.path.exists(pcmd):
            return pcmd

    return None


def __get_run_data(run_dir):
    run_xml = DashXMLLog.parse(run_dir)

    end_time = run_xml.end_time
    delta = end_time - run_xml.start_time
    try:
        # pylint: disable=no-member
        # PyLint thinks 'delta' is a 'float'
        duration = int(delta.seconds)
    except ValueError:
        duration = 0

    return (end_time, duration)


def __get_size(run_dir, run_num, logger=None):
    total = 0
    for entry in os.listdir(run_dir):
        path = os.path.join(run_dir, entry)

        if not os.path.isfile(path):
            if logger is not None:
                logger.error("Ignoring run %s subdirectory %s" %
                             (run_num, entry))
            continue

        total += os.path.getsize(path)

    return total


def __in_progress(logger, run_num):
    global CURRENT_RUN_NUMBER

    if CURRENT_RUN_NUMBER is None:
        cmd = __find_executable("livecmd")
        if cmd is None:
            # if we can't find the current run number,
            # assume 'run_num' is current
            logger.error("Cannot find 'livecmd' program")
            return True

        proc = subprocess.Popen([cmd, "check"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True)

        cur_num = None
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("run:"):
                try:
                    cur_num = int(line[4:])
                except ValueError:
                    logger.error("Bad livecmd run number line \"%s\"" % line)
                break

        proc.stdout.close()
        proc.wait()

        if cur_num is None:
            CURRENT_RUN_NUMBER = -1
        else:
            CURRENT_RUN_NUMBER = cur_num

    return CURRENT_RUN_NUMBER == run_num


def __indicate_daq_logs_queued(spade_dir, dry_run=False):
    __touch_file(os.path.join(spade_dir, FILE_MARKER), dry_run=dry_run)


def __sizefmt(size):
    for ext in ('bytes', 'KB', 'MB', 'GB'):
        if size < 1024.0:
            return "%3.1f %s" % (size, ext)
        size /= 1024.0
    return "%3.1f TB" % size


def __touch_file(filename, dry_run=False):
    if dry_run:
        print("touch %s" % filename)
    else:
        open(filename, "w").close()


def __write_spade_semaphore(spade_dir, spade_base_name, dry_run=False):
    sem_file = os.path.join(spade_dir, spade_base_name + ".sem")
    __touch_file(sem_file, dry_run=dry_run)


def __write_spade_tar_file(spade_dir, spade_base_name, run_dir, run_num,
                           logger=None, dry_run=False, force=False):
    # ignore huge directories
    dirsize = __get_size(run_dir, run_num, logger=logger)
    if dirsize >= TOO_LARGE and not force:
        if logger is not None:
            logger.error("Not sending %s; %s is too large" %
                         (run_dir, __sizefmt(dirsize)))
            return None

    tar_path = os.path.join(spade_dir, spade_base_name + ".dat.tar")

    if dry_run:
        print("tar cvf %s %s" % (tar_path, run_dir))
    else:
        tar_obj = tarfile.TarFile(tar_path, "w")
        tar_obj.add(run_dir, os.path.basename(run_dir), True)
        tar_obj.close()

    return tar_path


def add_arguments(parser):
    "Add command-line arguments"

    parser.add_argument("-a", "--check-all", dest="check_all",
                        action="store_true", default=False,
                        help="Queue all unqueued daqrun directories")
    parser.add_argument("-C", "--no-combine", dest="no_combine",
                        action="store_true", default=False,
                        help="Do not created a combined log file")
    parser.add_argument("-f", "--force", dest="force",
                        action="store_true", default=False,
                        help=("Requeue the logs for runs which have already"
                              " been queued"))
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help=("Don't create any files, just print what would"
                              " happen"))
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print running commentary of program's progress")
    parser.add_argument("run_number", nargs="*")


def check_all(logger, spade_dir, copy_dir, log_dir, no_combine=False,
              force=False, dry_run=False):
    if log_dir is None or not os.path.exists(log_dir):
        logger.info("Log directory \"%s\" does not exist" % log_dir)
        return

    for entry in os.listdir(log_dir):
        if entry.startswith("daqrun"):
            if os.path.exists(os.path.join(log_dir, entry, FILE_MARKER)):
                # skip runs which have already been queued
                continue

            try:
                run_num = int(entry[6:])
            except ValueError:
                logger.error("Bad run directory name \"%s\"" % entry)
                continue

            queue_for_spade(logger, spade_dir, copy_dir, log_dir, run_num,
                            no_combine=no_combine, force=force,
                            dry_run=dry_run)


def queue_for_spade(logger, spade_dir, copy_dir, log_dir, run_num,
                    no_combine=False, force=False, dry_run=False):
    if log_dir is None or not os.path.exists(log_dir):
        logger.error("Log directory \"%s\" does not exist" % log_dir)
        return

    run_dir = os.path.join(log_dir, "daqrun%05d" % run_num)
    if run_dir is None or not os.path.exists(run_dir):
        logger.error("Run directory \"%s\" does not exist" % run_dir)
        return

    if spade_dir is None or not os.path.exists(spade_dir):
        logger.error("SPADE directory \"%s\" does not exist" % spade_dir)
        return

    if os.path.exists(os.path.join(run_dir, FILE_MARKER)) and \
       not force:
        logger.error(("Logs for run %d have already been queued;" +
                      " Use --force to requeue them") % run_num)
        return

    try:
        (run_time, run_duration) = __get_run_data(run_dir)
    except FileNotFoundException:
        if __in_progress(logger, run_num):
            # don't try to queue log files from current run
            return
        (run_time, run_duration) = (None, 0)

    path = os.path.join(run_dir, COMBINED_LOG)
    if not os.path.exists(path):
        if no_combine:
            logger.error("Not writing combined log for run %d" % run_num)
        else:
            logger.error("Writing combined log for run %d" % run_num)
            lsrt = LogSorter(run_dir, run_num)
            # write to dotfile in case thread dies before it's finished
            tmppath = os.path.join(run_dir, "." + COMBINED_LOG)
            with open(tmppath, "w") as out:
                lsrt.dump_run(out)
            # it's now safe to rename the combined log file
            os.rename(tmppath, path)
            try:
                logger.error("Wrote combined log for run %d" % run_num)
            except:  # pylint: disable=bare-except
                # don't die if we lose the race to close the file
                pass

    if run_time is None:
        run_time = datetime.datetime.now()

    try:
        fmt_str = "SPS-pDAQ-run-%03d_%04d%02d%02d_%02d%02d%02d_%06d"
        spade_base_name = fmt_str % \
            (run_num, run_time.year, run_time.month, run_time.day,
             run_time.hour, run_time.minute, run_time.second, run_duration)

        tar_file = __write_spade_tar_file(spade_dir, spade_base_name, run_dir,
                                          run_num, logger=logger,
                                          dry_run=dry_run, force=force)
        if tar_file is not None:
            if copy_dir is not None and os.path.exists(copy_dir):
                __copy_spade_tar_file(logger, copy_dir, spade_base_name,
                                      tar_file, dry_run=dry_run)

            __write_spade_semaphore(spade_dir, spade_base_name,
                                    dry_run=dry_run)

            __indicate_daq_logs_queued(run_dir, dry_run=dry_run)

            logger.info(("Queued data for SPADE (spadeDir=%s" +
                         ", run_dir=%s, run_num=%s)...") %
                        (spade_dir, run_dir, run_num))
    except:  # pylint: disable=bare-except
        logger.error("FAILED to queue data for SPADE: " + exc_string())


def queue_logs(args):
    import logging

    logging.basicConfig()

    logger = logging.getLogger("spadeQueue")
    logger.setLevel(logging.DEBUG)

    cluster = ClusterDescription()
    spade_dir = cluster.log_dir_for_spade
    log_dir = cluster.daq_log_dir
    copy_dir = None

    if args.check_all or \
      len(args.run_number) == 0:  # pylint: disable=len-as-condition
        check_all(logger, spade_dir, copy_dir, log_dir,
                  no_combine=args.no_combine, force=args.force,
                  dry_run=args.dry_run)
    else:
        for numstr in args.run_number:
            run_num = int(numstr)

            queue_for_spade(logger, spade_dir, copy_dir, log_dir, run_num,
                            no_combine=args.no_combine, force=args.force,
                            dry_run=args.dry_run)


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    queue_logs(args)


if __name__ == "__main__":
    main()
