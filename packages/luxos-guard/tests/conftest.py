"""Testy Lux Guard: moduly ze zdrojoveho stromu (files/), bez __pycache__ v repozitari."""
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
sys.path.insert(0, os.path.abspath(FILES))
os.environ.setdefault("LUXOS_I18N_DIR", os.path.abspath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))
