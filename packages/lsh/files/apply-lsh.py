#!/usr/bin/env python3
"""Upravi zdrojaky GNU bash na lsh (Lux Shell).

  apply-lsh.py BASH_SRC_DIR LSH_VERSION

Kazda zmena musi v souboru najit presne jedno misto, jinak skript skonci
chybou (napr. po aktualizaci bashe, kdy je potreba upravy zkontrolovat).
"""
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
version = sys.argv[2]


def edit(name, old, new, count=1):
    path = src / name
    text = path.read_text()
    found = text.count(old)
    if found != count:
        sys.exit(f"apply-lsh: {name}: expected {count}x {old!r}, found {found}x")
    path.write_text(text.replace(old, new))


# Konfiguracni soubory a verze
edit("config-top.h", '#define DEFAULT_BASHRC "~/.bashrc"',
     f'#define DEFAULT_BASHRC "~/.lshrc"\n#define LSH_VERSION "{version}"')
edit("config-top.h", '/* #define SYS_BASHRC "/etc/bash.bashrc" */', '#define SYS_BASHRC "/etc/lsh/lshrc"')
edit("shell.c", '"~/.bash_profile"', '"~/.lsh_profile"')
edit("shell.c", '"~/.bash_login"', '"~/.lsh_login"')
edit("bashhist.c", '"~/.bash_history"', '"~/.lsh_history"')
edit("builtins/exit.def", '"~/.bash_logout"', '"~/.lsh_logout"')

# Interaktivni prihlasovaci shell (TTY, ssh) cte po profilu i lshrc
edit("shell.c", "      /* We don't execute .bashrc for login shells. */\n      no_rc++;\n",
     "      /* lsh: interaktivni login shell cte i lshrc */\n")
edit("shell.c", "\t  /* We don't execute .bashrc for login shells. */\n\t  no_rc++;\n",
     "\t  /* lsh: interaktivni login shell cte i lshrc */\n")

# Uklid relace LSL pri ukonceni shellu
edit("shell.c", "exit_shell (int s)\n{\n",
     "exit_shell (int s)\n{\n  extern void lsh_lsl_cleanup (void);\n  lsh_lsl_cleanup ();\n")

# Verze: lsh, zalozeny na GNU bash
edit("version.c", 'printf (_("GNU bash, version %s (%s)\\n"), shell_version_string (), MACHTYPE);',
     'printf ("lsh (Lux Shell) %s, based on GNU bash %s (%s)\\n", LSH_VERSION, shell_version_string (), MACHTYPE);')
edit("variables.c", '  bind_variable ("BASH_VERSION", shell_version_string (), 0);\n',
     '  bind_variable ("BASH_VERSION", shell_version_string (), 0);\n'
     '  bind_variable ("LSH_VERSION", LSH_VERSION, 0);\n')

# Radky LSL predat lsl jeste pred parserem (readline i eval z ble.sh)
edit("parse.y", "#endif /* HISTORY */\n\n      if (shell_input_line)\n",
     "#endif /* HISTORY */\n\n"
     "      /* lsh: radek LSL na zacatku prikazu prepsat na lsl-session run '...' */\n"
     "      if (shell_input_line && current_command_line_count == 1 && shell_eof_token == 0 &&\n"
     "\t  need_here_doc == 0 && current_delimiter (dstack) == 0)\n"
     "\t{\n"
     "\t  extern char *lsh_lsl_rewrite (const char *);\n"
     "\t  char *lsh_line = lsh_lsl_rewrite (shell_input_line);\n"
     "\t  if (lsh_line)\n"
     "\t    {\n"
     "\t      free (shell_input_line);\n"
     "\t      shell_input_line = lsh_line;\n"
     "\t      shell_input_line_len = strlen (shell_input_line);\n"
     "\t      shell_input_line_size = shell_input_line_len;\n"
     "\t      set_line_mbstate ();\n"
     "\t    }\n"
     "\t}\n\n"
     "      if (shell_input_line)\n")
# ./skript.lsl spustit pres lsl
edit("execute_cmd.c", "  SETOSTYPE (0);\t\t/* Some systems use for USG/POSIX semantics */\n  execve (command, args, env);\n",
     "  {\n"
     "    extern void lsh_exec_lsl_script (char *, char **, char **);\n"
     "    lsh_exec_lsl_script (command, args, env);\n"
     "  }\n"
     "  SETOSTYPE (0);\t\t/* Some systems use for USG/POSIX semantics */\n  execve (command, args, env);\n")

# Vestaveny prikaz about
edit("builtins/Makefile.in", "\t  $(srcdir)/times.def ", "\t  $(srcdir)/about.def $(srcdir)/times.def ")
edit("builtins/Makefile.in", "\tsuspend.o test.o times.o ", "\tsuspend.o test.o about.o times.o ")
edit("builtins/Makefile.in", "times.o: times.def\n", "times.o: times.def\nabout.o: about.def\n")
