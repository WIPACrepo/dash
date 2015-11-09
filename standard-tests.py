#!/usr/bin/env python
#
# Run standard pDAQ tests

from StandardTests import add_arguments, run_tests

if __name__ == "__main__":
    import argparse

    op = argparse.ArgumentParser()
    add_arguments(op)

    args = op.parse_args()

    run_tests(args)
