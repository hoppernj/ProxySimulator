import logging
import sys

rblog = logging.getLogger("rbridge")
rblog.setLevel(logging.DEBUG)

if not rblog.hasHandlers():
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    rblog.addHandler(handler)

