""" A module for parsing svn keywords, looking for the pDAQ release
name, 'trunk' or 'unknown' if neither can be found."""

import pprint

PP = pprint.PrettyPrinter(indent=2)

SVN_ID = "$Id: SVNVersionInfo.py 2226 2007-11-02 00:28:47Z ksb $"

# This will hold the global svn revision # for a release as determined
# by 'svnversion' at release time.  When on the trunk (not part of a
# release) this will be 0.
SVN_GLOBAL_REV = 0

# The release name, 'trunk' for unreleased, development versions
RELEASE = 'trunk'

def get_version_info(svn_id):

    """ Split provided subversion keyword Id value and return tuple of
    release identifiers: (filename, release, revision, date, time,
    author).  All values will be 'unknown' if there is a problem
    parsing input values."""

    ids = svn_id.split()
    # Check that svn_id has 7 fields, as the Id keyword should
    if len(ids) != 7:
        ids = ['unknown'] * 7

    return {'filename' : ids[1],
            'revision' : ids[2],
            'date'     : ids[3],
            'time'     : ids[4],
            'author'   : ids[5],
            'release'  : RELEASE,
            'repo_rev' : SVN_GLOBAL_REV}

if __name__ == '__main__':
    PP.pprint(get_version_info(SVN_ID))
    print "%(filename)s %(revision)s %(date)s %(time)s %(author)s "\
          "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
