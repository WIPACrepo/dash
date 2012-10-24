from validate_configs import validate_default_dom_geom
import os
import sys

if __name__ == "__main__":
    sys.path.append('..')
    from locate_pdaq import find_pdaq_config
    config_path = find_pdaq_config()
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
