#!/usr/bin/env python

import datetime
import logging
import os
import re
import struct
import tarfile

from lxml import etree

import h5py
import numpy

from DefaultDomGeometry import DefaultDomGeometryReader


# hack to simulate new DomGeometry.is_icetop property
def is_icetop(dom):
    return dom.pos() >= 61 and dom.pos() <= 64


##########################################
### Temporarily moved here from payload.py
class Payload(object):
    "Base payload class"
    TYPE_ID = None
    ENVELOPE_LENGTH = 16

    def __init__(self, utime, data, keep_data=True):
        "Payload time and non-envelope data bytes"
        self.__utime = utime
        if keep_data and data is not None:
            self.__data = data
            self.__valid_data = True
        else:
            self.__data = None
            self.__valid_data = False

    def __cmp__(self, other):
        "Compare envelope times"
        if self.__utime < other.utime:
            return -1
        if self.__utime > other.utime:
            return 1
        return 0

    @property
    def bytes(self):
        "Return the binary representation of this payload"
        if not self.__valid_data:
            raise PayloadException("Data was discarded; cannot return bytes")
        return self.envelope + self.__data

    @property
    def data_bytes(self):
        "Data bytes (should not include the 16 byte envelope)"
        if not self.__valid_data:
            raise PayloadException("Data was discarded; cannot return bytes")
        return self.__data

    @property
    def data_length(self):
        if not self.__valid_data:
            raise PayloadException("Data was discarded; cannot return length")
        return len(self.__data)

    @property
    def envelope(self):
        return struct.pack(">2IQ", self.data_length + self.ENVELOPE_LENGTH,
                           self.payload_type_id(), self.__utime)

    @property
    def has_data(self):
        "Did this payload retain the original data bytes?"
        return self.__valid_data

    @classmethod
    def payload_type_id(cls):
        "Integer value representing this payload's type"
        if cls.TYPE_ID is None:
            return NotImplementedError()
        return cls.TYPE_ID

    @staticmethod
    def source_name(src_id):
        "Translate the source ID into a human-readable string"
        comp_type = int(src_id / 1000)
        comp_num = src_id % 1000

        if comp_type == 3:
            return "icetopHandler-%d" % comp_num
        elif comp_type == 12:
            return "stringHub-%d" % comp_num
        elif comp_type == 13:
            return "simHub-%d" % comp_num

        if comp_type == 4:
            comp_name = "inIceTrigger"
        elif comp_type == 5:
            comp_name = "iceTopTrigger"
        elif comp_type == 6:
            comp_name = "globalTrigger"
        elif comp_type == 7:
            comp_name = "eventBuilder"
        elif comp_type == 8:
            comp_name = "tcalBuilder"
        elif comp_type == 9:
            comp_name = "moniBuilder"
        elif comp_type == 10:
            comp_name = "amandaTrigger"
        elif comp_type == 11:
            comp_name = "snBuilder"
        elif comp_type == 14:
            comp_name = "secondaryBuilders"
        elif comp_type == 15:
            comp_name = "trackEngine"

        if comp_num != 0:
            raise PayloadException("Unexpected component#%d for %s" %
                                   (comp_num, comp_name))

        return comp_name

    @property
    def utime(self):
        "UTC time from payload header"
        return self.__utime


class UnknownPayload(Payload):
    "A payload which has not been implemented in this library"

    def __init__(self, type_id, utime, data, keep_data=True):
        "Create an unknown payload"
        self.__type_id = type_id

        super(UnknownPayload, self).__init__(utime, data, keep_data=keep_data)

    def payload_type_id(self):
        "Integer value representing this payload's type"
        return self.__type_id

    def __str__(self):
        "Payload description"
        if self.has_data:
            lenstr = ", %d bytes" % (len(self.data_bytes) +
                                     self.ENVELOPE_LENGTH)
        else:
            lenstr = ""
        return "UnknownPayload#%d[@%d%s]" % \
            (self.__type_id, self.utime, lenstr)


class Monitor(object):
    TYPE_ID = 5

    def __init__(self):
        """
        Extract time calibration data from the buffer
        """
        raise NotImplementedError("Use Monitor.subtype()")

    @classmethod
    def subtype(cls, utime, data, keep_data=True):
        if len(data) < 12:
            raise PayloadException("Truncated monitoring record")

        subhdr = struct.unpack(">Qhh6B", data[:18])
        if subhdr[1] != len(data) - 8:
            raise PayloadException("Expected %d-byte record, not %d" %
                                   (subhdr[1], len(data) - 8))

        dom_id = subhdr[0]

        if subhdr[2] & 0xff > 0:
            rectype = subhdr[2] & 0xff
        else:
            rectype = (subhdr[2] >> 8) & 0xff

        domclock = subhdr[3:]

        if rectype == MonitorHardware.SUBTYPE_ID:
            return MonitorHardware(utime, dom_id, domclock, data[18:])
        if rectype == MonitorConfig.SUBTYPE_ID:
            return MonitorConfig(utime, dom_id, domclock, data[18:])
        if rectype == MonitorConfigChange.SUBTYPE_ID:
            return MonitorConfigChange(utime, dom_id, domclock, data[18:])
        if rectype == MonitorASCII.SUBTYPE_ID:
            return MonitorASCII(utime, dom_id, domclock, data[18:])
        if rectype == MonitorGeneric.SUBTYPE_ID:
            return MonitorGeneric(utime, dom_id, domclock, data[18:])

        return UnknownPayload(cls.TYPE_ID, utime, data, keep_data=keep_data)


class MonitorRecord(object):
    def __init__(self, utime, dom_id, domclock):
        self.__utime = utime
        self.__dom_id = dom_id
        self.__clockbytes = domclock

    @property
    def dom_id(self):
        return self.__dom_id

    @property
    def domclock(self):
        val = 0
        for byte in self.__clockbytes:
            val = (val << 8) + byte
        return val

    @property
    def utime(self):
        return self.__utime


class MonitorASCII(MonitorRecord):
    SUBTYPE_ID = 0xcb

    def __init__(self, utime, dom_id, domclock, data):
        self.__text = struct.unpack("%ds" % len(data), data)[0]

        super(MonitorASCII, self).__init__(utime, dom_id, domclock)

    def __str__(self):
        return "MonitorASCII@%d[dom %012x clk %d \"%s\"]" % \
            (self.utime, self.dom_id, self.domclock, self.__text)

    @property
    def subtype(self):
        return self.SUBTYPE_ID

    @property
    def text(self):
        return self.__text


class MonitorConfig(MonitorRecord):
    SUBTYPE_ID = 0xc9

    def __init__(self, utime, dom_id, domclock, data):
        self.__data = data

        super(MonitorConfig, self).__init__(utime, dom_id, domclock)

    def __str__(self):
        return "MonitorConfig@%d[dom %012x clk %d data*%d]" % \
            (self.utime, self.dom_id, self.domclock, len(self.__data))

    @property
    def subtype(self):
        return self.SUBTYPE_ID


class MonitorConfigChange(MonitorRecord):
    SUBTYPE_ID = 0xca

    def __init__(self, utime, dom_id, domclock, data):
        self.__data = data

        super(MonitorConfigChange, self).__init__(utime, dom_id, domclock)

    def __str__(self):
        return "MonitorConfigChange@%d[dom %012x clk %d data*%d]" % \
            (self.utime, self.dom_id, self.domclock, len(self.__data))

    @property
    def subtype(self):
        return self.SUBTYPE_ID


class MonitorGeneric(MonitorRecord):
    SUBTYPE_ID = 0xcc

    def __init__(self, utime, dom_id, domclock, data):
        self.__data = data

        super(MonitorGeneric, self).__init__(utime, dom_id, domclock)

    def __str__(self):
        return "MonitorGeneric@%d[dom %012x clk %d data*%d]" % \
            (self.utime, self.dom_id, self.domclock, len(self.__data))

    @property
    def data(self):
        return self.__data[:]

    @property
    def subtype(self):
        return self.SUBTYPE_ID


class MonitorHardware(MonitorRecord):
    SUBTYPE_ID = 0xc8

    def __init__(self, utime, dom_id, domclock, data):
        self.__data = data

        super(MonitorHardware, self).__init__(utime, dom_id, domclock)

    def __str__(self):
        return "MonitorHardware@%d[dom %012x clk %d data*%d]" % \
            (self.utime, self.dom_id, self.domclock, len(self.__data))

    @property
    def subtype(self):
        return self.SUBTYPE_ID


class PayloadReader(object):
    "Read DAQ payloads from a file"
    def __init__(self, filename, keep_data=True):
        """
        Open a payload file
        """
        if not os.path.exists(filename):
            raise PayloadException("Cannot read \"%s\"" % filename)

        if filename.endswith(".gz"):
            fin = gzip.open(filename, "rb")
        elif filename.endswith(".bz2"):
            fin = bz2.BZ2File(filename)
        else:
            fin = open(filename, "rb")

        self.__filename = filename
        self.__fin = fin
        self.__keep_data = keep_data
        self.__num_read = 0L

    def __enter__(self):
        """
        Return this object as a context manager to used as
        `with PayloadReader(filename) as payrdr:`
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Close the open filehandle when the context manager exits
        """
        self.close()

    def __iter__(self):
        """
        Generator which returns payloads in `for payload in payrdr:` loops
        """
        while True:
            if self.__fin is None:
                # generator has been explicitly closed
                return

            # decode the next payload
            pay = self.next()
            if pay is None:
                # must have hit the end of the file
                return

            # return the next payload
            yield pay

    def close(self):
        """
        Explicitly close the filehandle
        """
        if self.__fin is not None:
            try:
                self.__fin.close()
            finally:
                self.__fin = None

    @property
    def nrec(self):
        "Number of payloads read to this point"
        return self.__num_read

    @property
    def filename(self):
        "Name of file being read"
        return self.__filename

    @classmethod
    def decode_payload(cls, stream, keep_data=True):
        """
        Decode and return the next payload
        """
        envelope = stream.read(Payload.ENVELOPE_LENGTH)
        if len(envelope) == 0:
            return None

        length, type_id, utime = struct.unpack(">iiq", envelope)
        if length <= Payload.ENVELOPE_LENGTH:
            rawdata = None
        else:
            rawdata = stream.read(length - Payload.ENVELOPE_LENGTH)

        if type_id == Monitor.TYPE_ID:
            return Monitor.subtype(utime, rawdata, keep_data=keep_data)

        return UnknownPayload(type_id, utime, rawdata, keep_data=keep_data)

    def next(self):
        "Read the next payload"
        pay = self.decode_payload(self.__fin, keep_data=self.__keep_data)
        self.__num_read += 1
        return pay
### Temporarily moved here from payload.py
##########################################


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


def convert_pairs_to_xml(root, pairs):
    """
    Add a list/tuple of lists/tuples of pairs of data to an XML tree.
    The 'pairs' list is a dumber version of an ordered dictionary
    """
    for key, val in pairs:
        node = etree.SubElement(root, key)
        if isinstance(val, tuple) or isinstance(val, list):
            convert_pairs_to_xml(node, val)
        else:
            node.text = str(val)


def create_meta_xml(path, suffix, run_number, verbose=False, dry_run=False):
    """
    Create a metadata file for JADE.  Metadata specification is at:
    https://docushare.icecube.wisc.edu/dsweb/Get/Document-20546/metadata_specification.pdf
    """

    # give up if they're passing us a bad filename/suffix pair
    if not path.endswith(suffix):
        raise SystemExit("File \"%s\" does not end with \"%s\"" %
                         (path, suffix))

    # define all the static fields
    title = "Icetop Scaler Data" #"IceTop_Scaler"
    summary = title
    category = "monitoring"
    subcategory = "IceTopScaler"

    # we'll need the file creation date for a few fields
    if dry_run:
        filetime = datetime.datetime.now()
    else:
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            raise SystemExit("Cannot write metadata file: %s does not exist" %
                             (path, ))
        filetime = datetime.datetime.fromtimestamp(stamp)

    # we'll need the directory and base filename below
    directory = os.path.dirname(path)
    basename = os.path.basename(path)[:-len(suffix)]
    if basename[-1] == ".":
        basename = basename[:-1]

    # fill in all the file-related fields
    timestr = filetime.strftime("%Y-%m-%dT%H:%M:%S")
    plus_fields = (
        ("Start_DateTime", timestr),
        ("End_DateTime", timestr),
        ("Category", category),
        ("Subcategory", subcategory),
        ("Run_Number", run_number),
    )

    xmldict = (
        ("DIF", (
            ("Entry_ID", basename),
            ("Entry_Title", title),
            ("Parameters",
             "SPACE SCIENCE > Astrophysics > Neutrinos"),
            ("ISO_Topic_Category", "geoscientificinformation"),
            ("Data_Center", (
                ("Data_Center_Name",
                 "UWI-MAD/A3RI > Antarctic Astronomy and Astrophysics"
                 " Research Institute, University of Wisconsin, Madison"),
                ("Personnel", (
                    ("Role", "Data Center Contact"),
                    ("Email", "datacenter@icecube.wisc.edu"),
                )),
            )),
            ("Summary", summary),
            ("Metadata_Name", "[CEOS IDN DIF]"),
            ("Metadata_Version", "9.4"),
            ("Personnel", (
                ("Role", "Technical Contact"),
                ("First_Name", "Dave"),
                ("Last_Name", "Glowacki"),
                ("Email", "dglo@icecube.wisc.edu"),
            )),
            ("Sensor_Name", "ICECUBE > IceCube"),
            ("Source_Name",
             "EXPERIMENTAL > Data with an instrumentation based"
             " source"),
            ("DIF_Creation_Date", filetime.strftime("%Y-%m-%d")),
        )),
        ("Plus", plus_fields),
    )

    root = etree.Element("DIF_Plus")
    root.set("{http://www.w3.org/2001/XMLSchema-instance}"
             "noNamespaceSchemaLocation", "IceCubeDIFPlus.xsd")

    convert_pairs_to_xml(root, xmldict)

    metaname = basename + ".meta.xml"
    if verbose:
        print "Creating JADE semaphore file %s" % (metaname, )
    if not dry_run:
        with open(os.path.join(directory, metaname), "w") as out:
            out.write(etree.tostring(root))

    return metaname


def process_moni(dom_dict, moniname):
    """
    Return a list of all IceTop "fast" monitoring records in this file
    """
    data = []
    with PayloadReader(moniname) as rdr:
        for pay in rdr:
            if not isinstance(pay, MonitorRecord):
                logging.error("Ignoring %s payload %s", moniname, pay)
                continue

            if pay.subtype != MonitorASCII.SUBTYPE_ID:
                # only want ASCII records
                continue

            key = "%012x" % pay.dom_id
            if key not in dom_dict:
                logging.error("Ignoring unknown DOM %012x", key)
                continue

            dom = dom_dict[key]
            if not is_icetop(dom):
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


def process_list(monilist, dom_dict, verbose=False, dry_run=False, debug=False):
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
            write_data(run, data, verbose=verbose, dry_run=dry_run,
                       make_meta_xml=True)
            del data[:]

        # save the new data
        run = frun
        if verbose:
            print "Processing run %d moni file #%d" % (frun, fseq)
        data += process_moni(dom_dict, moni)

    if run is not None:
        write_data(run, data, verbose=verbose, dry_run=dry_run,
                   make_meta_xml=True)


def process_tar_file(tarname, dom_dict, verbose=False, debug=True):
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
            write_data(run, data, verbose=verbose)
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
        write_data(run, data, verbose=verbose)


def write_data(run, data, verbose=False, dry_run=False, make_meta_xml=False):
    "Write IceTop monitoring data to an HDF5 file"

    # ignore empty arrays
    if data is None or len(data) == 0:
        return

    # define file suffix here since we'll need it in a couple of places
    suffix = ".hdf5"

    # assemble the base name for the file
    now = datetime.datetime.now()
    basename = "IceTop_%06d_%04d%02d%02d_%02d%02d%02d" % \
               (run, now.year, now.month, now.day, now.hour, now.minute,
                now.second)

    # find the next unused filename
    seq = 0
    while True:
        filename = "%s_%d%s" % (basename, seq, suffix)
        if not os.path.exists(filename):
            break
        seq += 1

    if verbose:
        print "Writing %s" % (filename, )

    # write data
    if not dry_run:
        with h5py.File(filename, "w") as out:
            # create a NumPy array from the data
            narray = numpy.array(data, dtype=H5_TYPES)
            # add the data to the file
            out.create_dataset("FastIceTop", data=narray, chunks=True)

    if make_meta_xml:
        create_meta_xml(filename, suffix, run, verbose=verbose, dry_run=dry_run)


if __name__ == "__main__":
    #pylint: disable=invalid-name,wrong-import-position
    import sys

    verbose = False
    files = []
    for fname in sys.argv[1:]:
        if fname == "-v":
            verbose = True
        elif os.path.exists(fname):
            files.append(fname)
        else:
            logging.error("Ignoring unknown file \"%s\"", fname)

    # read in default-dom-geometry.xml
    ddg = DefaultDomGeometryReader.parse(translateDoms=True)

    # cache the DOM ID -> DOM dictionary
    ddict = ddg.getDomIdToDomDict()

    for fname in files:
        process_tar_file(fname, ddict, verbose=verbose)
