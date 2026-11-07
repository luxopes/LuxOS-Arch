"""Testy Lux Guard: moduly ze zdrojoveho stromu (files/), bez __pycache__ v repozitari."""
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
sys.path.insert(0, os.path.abspath(FILES))
os.environ.setdefault("LUXOS_I18N_DIR", os.path.abspath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))

# Vsechny moduly hned ze zdroju: luxos_guard_session (i agent) si pri importu pridava na zacatek sys.path
# /usr/lib/luxos/python - pozdejsi import by jinak nacetl nainstalovanou (starsi) verzi.
import luxos_guard_core  # noqa: E402,F401
import luxos_guard_rules  # noqa: E402,F401
import luxos_guard_service  # noqa: E402,F401
import luxos_guard_snap  # noqa: E402,F401
import luxos_guard_session  # noqa: E402,F401
