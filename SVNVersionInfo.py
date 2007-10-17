""" A module for parsing svn keywords, looking for the pDAQ release
name, 'trunk' or 'unknown' if neither can be found."""

import re

SVN_ID = "$Id: SVNVersionInfo.py 2146 2007-10-17 01:37:59Z ksb $"
SVN_URL = "$URL: http://code.icecube.wisc.edu/daq/projects/dash/trunk/SVNVersionInfo.py $"

# This will hold the global svn revision # for a release as determined
# by 'svnversion' at release time.  When on the trunk (not part of a
# release) this will be 0.
SVN_GLOBAL_REV = 0

def getVersionInfo(svn_id, svn_url):

    """ Search provided subversion keyword values Id and URL and
    return tuple of release identifiers: (filename, release, revision,
    date, time, author) where release is the release name or 'trunk'
    (as extracted from the svn_url).  All values will be 'unknown' if
    there is a problem parsing input values."""

    # The default value (for all fields).
    release = "unknown"

    ids = svn_id.split()
    # Check that svn_id has 7 fields, as the Id keyword should
    if len(ids) != 7:
        ids = [release for x in range(7)]

    trunk_search = re.search(r'/(trunk)/.*/?' + ids[1], svn_url)
    if trunk_search:
        release = trunk_search.group(1)
    else:
        release_search = re.search(r'/releases/(.*?)/.*/?' + ids[1], svn_url)
        if release_search:
            release = release_search.group(1)

    return {'filename' : ids[1],
            'revision' : ids[2],
            'date'     : ids[3],
            'time'     : ids[4],
            'author'   : ids[5],
            'release'  : release,
            'repo_rev' : SVN_GLOBAL_REV}

if __name__ == '__main__':
    print getVersionInfo(SVN_ID, SVN_URL)
    print "%(filename)s %(revision)s %(date)s %(time)s %(author)s %(release)s %(repo_rev)s" % getVersionInfo(SVN_ID, SVN_URL)
