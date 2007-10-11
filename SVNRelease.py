""" A module for parsing svn keywords, looking for the pDAQ release
name, 'trunk' or 'unknown' if neither can be found."""

import re

svn_id = "$Id: SVNRelease.py 2116 2007-10-11 22:47:55Z ksb $"
svn_url = "$URL: http://code.icecube.wisc.edu/daq/projects/dash/trunk/SVNRelease.py $"

def getReleaseInfo(svn_id, svn_url):

    """ Search provided subversion keyword values Id and URL and
    return tuple of release identifiers: (release, revision, date,
    time, author, filename) where release is the release name or
    'trunk'.  All values will be 'unknown' if there is a problem
    parsing input values."""

    # The default value.
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

    return release, ids[2], ids[3], ids[4], ids[5]

if __name__ == '__main__':
    print getReleaseInfo(svn_id, svn_url)
