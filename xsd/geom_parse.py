from validate_configs import validate_default_dom_geom
import os
import sys

if __name__ == "__main__":
    # Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
    if "PDAQ_HOME" in os.environ:
        metaDir = os.environ["PDAQ_HOME"]
    else:
        sys.path.append('..')
        from locate_pdaq import find_pdaq_trunk
        metaDir = find_pdaq_trunk()

    config_path = os.path.join(metaDir, "config")
    default_dom_geometry_path = os.path.join(config_path,
                                             'default-dom-geometry.xml')

    valid, reason = validate_default_dom_geom(default_dom_geometry_path)
    if not valid:
        print "File is not valid!"
        print "-" * 60
        print ""
        print reason
    else:
        print "Valid"
