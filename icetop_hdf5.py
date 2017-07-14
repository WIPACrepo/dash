#!/usr/bin/env python

import logging
import os
import re
import tarfile

import h5py
import numpy
import payload

from DefaultDomGeometry import DefaultDomGeometryReader


MONI_PAT = re.compile(r"^moni_(\d+)_(\d+)_\d+_\d+\.dat$")

H5_TYPES = [
    ('DOM_String', '<u2'),
    ('DOM_Position', '<u2'),
    ('SPE', '<u4'),
    ('MPE', '<u4'),
    ('HITS', 'u4'),
    ('DEADTIME', '<u4'),
    ('UT', '<u8'),
]


def process_moni(dom_dict, moniname):
    """
    Return a list of all IceTop "fast" monitoring records in this file
    """
    data = []
    with payload.PayloadReader(moniname) as rdr:
        for pay in rdr:
            if not isinstance(pay, payload.MonitorRecord):
                logging.error("Ignoring %s payload %s", moniname, pay)
                continue

            if pay.subtype != payload.MonitorASCII.SUBTYPE_ID:
                # only want ASCII records
                continue

            key = "%012x" % pay.dom_id
            if key not in dom_dict:
                logging.error("Ignoring unknown DOM %012x", key)
                continue

            dom = dom_dict[key]
            if not dom.is_icetop:
                continue

            if not pay.text.startswith("F "):
                # only want FAST records
                continue

            flds = []
            for tmp in pay.text[2:].split():
                try:
                    flds.append(int(tmp))
                except ValueError:
                    logging.error("Bad FAST data \"%s\"", pay.text)
                    continue

            if len(flds) != 4:
                logging.error("Too many fields in FAST data \"%s\"", pay.text)
                continue

            (spe_count, mpe_count, launches, deadtime) = flds
            data.append((dom.originalString(), dom.pos(), spe_count, mpe_count,
                         launches, deadtime, pay.utime))

    return data


def process_list(monilist, dom_dict, verbose=False, debug=False):
    "Process all .moni files in the list"
    run = None
    data = []

    for moni in monilist:
        match = MONI_PAT.match(moni)
        if match is None:
            if debug:
                print "BADNAME %s" % (moni, )
            continue

        # get the run number from the file name
        frun = int(match.group(1))
        fseq = int(match.group(2))

        # if we've got data from another run, write it to a file
        if run is not None and run != frun:
            write_data(run, data, verbose=verbose)
            del data[:]

        # save the new data
        run = frun
        if verbose:
            print "Processing run %d moni file #%d" % (frun, fseq)
        data += process_moni(dom_dict, moni)

    if run is not None:
        write_data(run, data, verbose=verbose)


def process_tar_file(tarname, dom_dict, debug=True):
    "Process all .moni files in the tar file"
    run = None
    data = []

    tfl = tarfile.open(tarname, "r")
    for info in tfl.getmembers():
        if not info.isfile():
            if debug:
                print "NONFILE[%s] %s" % (tarname, info.name, )
            continue

        if info.name.find("moni_") < 0:
            if debug:
                print "NONMONI[%s] %s" % (tarname, info.name)
            continue

        match = MONI_PAT.match(info.name)
        if match is None:
            if debug:
                print "BADNAME[%s] %s" % (tarname, info.name)
            continue

        # get the run number from the file name
        frun = int(match.group(1))

        # if we've got data from another run, write it to a file
        if run is not None and run != frun:
            write_data(run, data)
            del data[:]

        # extract this file from the tarfile
        tfl.extract(info)

        try:
            # save the new data
            run = frun
            data += process_moni(dom_dict, info.name)
        finally:
            os.unlink(info.name)

    if run is not None:
        write_data(run, data)


def write_data(run, data, verbose=False):
    "Write IceTop monitoring data to an HDF5 file"

    # ignore empty arrays
    if data is None or len(data) == 0:
        return

    # find the next unused filename
    seq = 1
    while True:
        filename = "IceTop-%06d-%d.hdf5" % (run, seq)
        if not os.path.exists(filename):
            break
        seq += 1

    if verbose:
        print "Writing %s" % (filename, )

    # write data
    with h5py.File(filename, "w") as out:
        # create a NumPy array from the data
        narray = numpy.array(data, dtype=H5_TYPES)
        # add the data to the file
        out.create_dataset("FastIceTop", data=narray, chunks=True)


if __name__ == "__main__":
    #pylint: disable=invalid-name,wrong-import-position
    import sys

    files = []
    for fname in sys.argv[1:]:
        if os.path.exists(fname):
            files.append(fname)
        else:
            logging.error("Ignoring unknown file \"%s\"", fname)

    # read in default-dom-geometry.xml
    ddg = DefaultDomGeometryReader.parse(translateDoms=True)

    # cache the DOM ID -> DOM dictionary
    ddict = ddg.getDomIdToDomDict()

    for fname in files:
        process_tar_file(fname, ddict)
