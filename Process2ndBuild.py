#!/usr/bin/env python

"""
Process2ndBuild.py
Jacobsen, back in the 2007's or so

This script is installed on 2ndbuild, collects the output of 2ndbuild
as it appears on /mnt/data/pdaqlocal, tars them in groups as they
appear, makes hard links for I3Moni, SNDAQ and SPADE, and puts the
appropriate semaphores in place.

It should be installed and activated (in cron) by the pDAQ Fabric
installation procedure.
"""

import datetime
import os
import tarfile
import time

import icetop_hdf5

from DefaultDomGeometry import DefaultDomGeometryReader
from NewProcess import exclusive_process

MAX_FILES_PER_TARBALL = 50


def is_target_file(filename):
    "Does this file start with 'moni', 'sn', or 'tcal'?"
    if filename is None:
        return False

    return filename.startswith("moni_") or filename.startswith("sn_") or \
        filename.startswith("tcal_")


def process_files(filelist, verbose=False, dry_run=False,
                  enable_moni_link=False, create_icetop_hdf5=False):
    # Make list for tarball - restrict total number of files
    files_to_tar = []
    moni_files = []
    while len(filelist) > 0:
        files_to_tar.append(filelist[0])
        if create_icetop_hdf5 and filelist[0].startswith("moni_"):
            moni_files.append(filelist[0])
        del filelist[0]
        if len(files_to_tar) >= MAX_FILES_PER_TARBALL:
            break

    if len(files_to_tar) == 0:
        return False

    create_tar_and_sem_files(files_to_tar, verbose=verbose, dry_run=dry_run,
                             enable_moni_link=enable_moni_link)

    if create_icetop_hdf5 and len(moni_files) > 0:
        # read in default-dom-geometry.xml
        ddg = DefaultDomGeometryReader.parse(translateDoms=True)

        # cache the DOM ID -> DOM dictionary
        dom_dict = ddg.getDomIdToDomDict()

        icetop_hdf5.process_list(moni_files, dom_dict, verbose=verbose,
                                 dry_run=dry_run)

    # Clean up tar'ed files
    for fname in files_to_tar:
        if verbose:
            print "Removing %s..." % (fname, )
        if not dry_run:
            os.unlink(fname)

    return True


def create_tar_and_sem_files(files_to_tar, verbose=False, dry_run=False,
                             enable_moni_link=False):
    if verbose:
        print "Found %d files" % len(files_to_tar)
    now = datetime.datetime.now()
    date_tag = "%03d_%04d%02d%02d_%02d%02d%02d_%06d" % \
        (0, now.year, now.month, now.day, now.hour, now.minute, now.second, 0)
    front = "SPS-pDAQ-2ndBld-" + date_tag
    spade_tar = front + ".dat.tar"
    spade_sem = front + ".sem"
    monilink = front + ".mon.tar"
    moni_sem = front + ".msem"
    snlink = front + ".sn.tar"

    # Duplicate file: wait for a new second, recalculate everything:
    if os.path.exists(spade_tar):
        time.sleep(1)
        return True

    # Create temporary tarball
    tmp_tar = "tmp-" + date_tag + ".tar"
    if verbose:
        print "Creating temporary tarball"
    try:
        if not dry_run:
            tarball = tarfile.open(tmp_tar, "w")
        for tfile in files_to_tar:
            if verbose:
                print "  " + tfile
            if not dry_run:
                tarball.add(tfile)
        if not dry_run:
            tarball.close()
    except:
        os.unlink(tmp_tar)
        raise
    if verbose:
        print "Done."

    # Rename temporary tarball to SPADE name
    if verbose:
        print "Renaming temporary tarball to %s" % spade_tar
    if not dry_run:
        os.rename(tmp_tar, spade_tar)

    # Create moni hard link
    if enable_moni_link:
        if verbose:
            print "MoniLink %s" % monilink
        if not dry_run:
            os.link(spade_tar, monilink)

    # Create sn hard link
    if verbose:
        print "SNLink %s" % snlink
    if not dry_run:
        os.link(spade_tar, snlink)
        # So that SN process can delete if it's not running as pdaq
        os.chmod(snlink, 0666)

    # Create spade .sem
    if not dry_run:
        sem = open(spade_sem, "w")
        sem.close()

    # Create monitoring .msem
    if enable_moni_link and not dry_run:
        sem = open(moni_sem, "w")
        sem.close()


def main(spade_dir, verbose=False, dry_run=False, enable_moni_link=False,
         create_icetop_hdf5=False):
    os.chdir(spade_dir)

    # Get list of available files, matching target tar pattern:
    filelist = []
    for fname in os.listdir(spade_dir):
        if is_target_file(fname):
            filelist.append(fname)

    filelist.sort(lambda x, y: (cmp(os.stat(x)[8], os.stat(y)[8])))

    process_files(filelist, verbose=verbose, dry_run=dry_run,
                  enable_moni_link=enable_moni_link,
                  create_icetop_hdf5=create_icetop_hdf5)


if __name__ == "__main__":
    #pylint: disable=invalid-name,wrong-import-position
    import argparse

    from ClusterDescription import ClusterDescription

    op = argparse.ArgumentParser()
    op.add_argument("-5", "--icetop-hdf5", dest="create_icetop_hdf5",
                    action="store_false", default=True,
                    help="Do NOT create HDF5 files for IceTop")
    op.add_argument("-d", "--spadedir", dest="spadedir",
                    action="store", default=None,
                    help="SPADE directory")
    op.add_argument("-m", "--enable-moni-link", dest="enable_moni_link",
                    action="store_true", default=False,
                    help="Include moni files and create a moni link")
    op.add_argument("-n", "--dry-run", dest="dry_run",
                    action="store_true", default=False,
                    help="Do not actually do anything")
    op.add_argument("-q", "--quiet", dest="verbose",
                    action="store_false", default=False,
                    help="Do not print log of actions to console")
    op.add_argument("-v", "--verbose", dest="verbose",
                    action="store_true", default=False,
                    help="Print log of actions to console (default)")

    args = op.parse_args()

    if args.spadedir is not None:
        spade_dir = os.path.abspath(args.spadedir)
    else:
        cluster = ClusterDescription()
        spade_dir = cluster.logDirForSpade

    # use '.pid' file to ensure multiple instances aren't
    # adding the same files to different tar files
    guard_file = os.path.join(os.environ["HOME"], ".proc2ndbld.pid")
    with exclusive_process(guard_file):
        main(spade_dir, verbose=args.verbose, dry_run=args.dry_run,
             enable_moni_link=args.enable_moni_link,
             create_icetop_hdf5=args.create_icetop_hdf5)
