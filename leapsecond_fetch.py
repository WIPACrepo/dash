#!/usr/bin/env python

from __future__ import print_function

import socket
import re
import os
import shutil

from ftplib import FTP
from leapseconds import LeapSeconds


def compare_latestleap(latest, filename, verbose=False):
    # load in the new file
    try:
        newleap = LeapSeconds(filename)
    except:  # pylint: disable=bare-except
        print("Downloaded NIST file %s is not valid" % filename)
        import traceback
        traceback.print_exc()
        return False

    # if latest file does not exist, we're done
    if not os.path.exists(latest):
        return True

    # load in the latest file
    try:
        oldleap = LeapSeconds(latest)
    except:  # pylint: disable=bare-except
        print("Replacing invalid %s" % latest)
        return True

    # compare expiry date/times for new file and installed latest file
    if oldleap.expiry < newleap.expiry:
        if verbose:
            print("Current file expiry (%s) is older than %s expiry (%s)" %
                  (oldleap.expiry, filename, newleap.expiry))
        return True

    # let user know that the new file is not newer than the installed file
    if verbose:
        if oldleap.expiry == newleap.expiry:
            print("A leapsecond file with this expiry date"
                  " has already been installed")
        else:
            print("%s has an older expiry date (%s) than the currently"
                  " installed version (%s)" %
                  (filename, newleap.expiry, oldleap.expiry))

    return False


def fetch_latestleap(host='tycho.usno.navy.mil', path='/pub/ntp',
                     verbose=False):
    try:
        ftp = FTP(host)
    except socket.error:
        print("Failed to connect to host: '%s'" % host)
        return None

    if verbose:
        print("Starting FTP session with %s" % host)
    ftp.login()

    if verbose:
        print("Changing to %s directory %s" % (host, path))
    ftp.cwd(path)

    if verbose:
        print("Listing %s" % path)
    file_list = ftp.nlst()

    # we are only interested in files that match the pattern
    # leap-seconds.nnnnnnnn

    lsec_pattern = re.compile(r'^leap-seconds\.([0-9]*)$')
    times_list = []
    match_dict = {}
    for fname in file_list:
        mtch = lsec_pattern.match(fname)
        if mtch is not None:
            file_time = int(mtch.group(1))
            match_dict[file_time] = fname
            times_list.append(file_time)

    if len(times_list) == 0:  # pylint: disable=len-as-condition
        print("Did not find any leap second files @ ftp://%s%s" % (host, path))
        ftp.close()
        return None

    latest_time = max(times_list)
    latest_file = match_dict[latest_time]

    # From the folks at nist:
    # Levine, Judah Dr. judah.levine@nist.gov via icecube.wisc.edu
    # to Matt
    # Hello,
    # The expiration date of the file is changed as I get new information
    # from the International Earth Rotation Service (IERS) about future leap
    # seconds. The extension changes ONLY when a new leap second has been
    # announced. So, if the extension is unchanged, then no new leap second
    # is pending. If the expiration date has changed then this is based on
    # new information from the IERS.
    #
    # ANNOYING...  no way to check and see if the file has been updated
    # without fetching it

    if verbose:
        print("A fetching: %s" % latest_file)
    ftp.retrbinary('RETR %s' % latest_file,
                   open(latest_file, 'wb').write)
    ftp.close()

    if verbose:
        print("Fetch complete")

    return latest_file


def install_latestleap(latest, filename, verbose=False):
    if os.path.exists(latest) and not os.path.islink(latest):
        # if 'latest' file is not a symlink, rename the old file
        # and move the new file in using that name
        old = latest + ".old"
        if os.path.exists(old):
            os.remove(old)
        if os.path.exists(latest):
            shutil.move(latest, old)
            if verbose:
                print("Backed up old %s" % latest)
        shutil.move(filename, latest)
        if verbose:
            print("Moved %s into place as %s" % (filename, latest))
    else:
        # if 'latest' doesn't exist or is a symlink, move the new file into
        # the same directory as 'latest' and point 'latest' at the new file
        ldir = os.path.dirname(latest)
        basename = os.path.basename(filename)

        # if the directory doesn't exist, try to create it
        if not os.path.exists(ldir):
            try:
                os.makedirs(ldir)
            except Exception as ex:
                raise SystemExit("Cannot create %s: %s" % (ldir, ex))

        newpath = os.path.join(ldir, basename)
        if os.path.exists(newpath):
            os.remove(newpath)
            if verbose:
                print("Removed old %s" % newpath)

        shutil.move(filename, newpath)

        try:
            os.remove(latest)
        except:  # pylint: disable=bare-except
            pass  # ignore all errors
        os.symlink(basename, latest)

        if verbose:
            print("Moved %s to %s and updated %s symlink" %
                  (basename, ldir, os.path.basename(latest)))


def main():
    "Main program"

    import sys

    verbose = len(sys.argv) > 1 and sys.argv[1] == "-v"

    latest = LeapSeconds.get_latest_path()

    newfile = fetch_latestleap(host='ftp.nist.gov',
                               path='/pub/time/', verbose=verbose)

    if compare_latestleap(latest, newfile, True):
        install_latestleap(latest, newfile, True)


if __name__ == "__main__":
    main()
