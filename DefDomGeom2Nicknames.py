#!/usr/bin/env python
"""
Use default-dom-geometry.xml to create a nicknames.txt file and print the
result to sys.stdout
"""

from __future__ import print_function

import sys

from DefaultDomGeometry import DefaultDomGeometryReader, NicknameReader

def dump_nicknames(geom, out=sys.stdout):
    "Dump the DOM data in nicknames.txt format"
    all_doms = []
    for dom in geom.doms():
        all_doms.append(dom)

    all_doms.sort(cmp=lambda x, y: cmp(x.name.lower(), y.name.lower()))

    print("mbid\tthedomid\tthename\tlocation\texplanation", file=out)
    for dom in all_doms:
        if dom.prod_id is None:
            continue
        if dom.string not in NicknameReader.SPECIAL_STRINGS and \
          dom.string >= 1000:
            continue

        name = dom.name.encode("iso-8859-1")

        if dom.description is None:
            desc = ""
        else:
            try:
                desc = dom.description.encode("iso-8859-1")
            except:
                desc = "-"

        if dom.original_string is None:
            str_num = dom.string
        else:
            str_num = dom.original_string

        if str_num is None:
            sstr = "??"
        elif str_num in NicknameReader.SPECIAL_STRINGS:
            sstr = str(str_num)
        else:
            sstr = "%02d" % str_num

        if dom.pos is None:
            pstr = "??"
        else:
            pstr = "%02d" % dom.pos

        print("%s\t%s\t%s\t%s-%s\t%s" % \
              (dom.mbid, dom.prod_id, name, sstr, pstr, desc),
              file=out)

def main():
    "Main program"
    # read in default-dom-geometry.xml
    if len(sys.argv) <= 1:
        geom = DefaultDomGeometryReader.parse()
    else:
        geom = DefaultDomGeometryReader.parse(file_name=sys.argv[1])

    NicknameReader.parse(def_dom_geom=geom)

    # dump the new default-dom-geometry data to sys.stdout
    dump_nicknames(geom)

if __name__ == "__main__":
    main()
