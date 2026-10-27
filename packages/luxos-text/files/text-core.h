/*
 * LuxOS Textovy editor - logika bez okna (kodovani, konce radku, pocty, jazyk, osnova, nedavne soubory).
 * Testuje tests/test-core.c bez obrazovky.
 */
#ifndef LUXOS_TEXT_CORE_H
#define LUXOS_TEXT_CORE_H

#include <glib.h>
#include <gtksourceview/gtksource.h>

typedef enum { TX_LF = 0, TX_CRLF = 1, TX_CR = 2 } TxLineEnd;

typedef struct {
    const char *id;       /* stabilni jmeno (nastaveni, testy) */
    const char *iconv;    /* jmeno pro g_convert */
    const char *region;   /* anglicky nazev skupiny (prekladat T()), NULL = Unicode */
    const char *name;     /* zobrazene jmeno kodovani */
    int bom;              /* pri ulozeni zapsat BOM */
    int unit;             /* bajtu na znak: 1 = jednobajtove, 2 = UTF-16, 0 = promenna delka */
} TxEncoding;

extern const TxEncoding tx_encodings[];
extern const int tx_n_encodings;

const TxEncoding *tx_encoding_find(const char *id);
const TxEncoding *tx_encoding_utf8(void);

/* Rozpozna kodovani (BOM, UTF-8, UTF-16 bez BOM, jednobajtova kodovani podle jazyka). lang = "cs", "de"...
 * NULL = binarni soubor (nulove bajty). */
const TxEncoding *tx_detect_encoding(const char *data, gsize len, const char *lang);
/* Prevod do UTF-8 (bez BOM, konce radku beze zmeny); NULL pri chybe */
char *tx_decode(const char *data, gsize len, const TxEncoding *enc, gsize *out_len, GError **err);
/* Prevazujici konec radku (zadny = LF) */
TxLineEnd tx_detect_line_ending(const char *s, gsize len);
gboolean tx_has_mixed_line_endings(const char *s, gsize len);
/* CRLF a CR -> LF (vraci novy retezec) */
char *tx_normalize_newlines(const char *s, gsize len, gsize *out_len);
/* Text s LF -> bajty k ulozeni (konce radku, kodovani, BOM); NULL pri neprevoditelnem znaku */
char *tx_encode(const char *s, gsize len, const TxEncoding *enc, TxLineEnd le, gsize *out_len, GError **err);
const char *tx_line_ending_name(TxLineEnd le);   /* "LF", "CRLF", "CR" */
int tx_line_ending_from_name(const char *name);  /* -1 = nezname */

typedef struct {
    gint64 lines;   /* 0 pro prazdny text, jinak pocet LF + 1 */
    gint64 chars;   /* znaky (kodove body) bez koncu radku */
    gint64 words;
    gint64 bytes;   /* velikost po ulozeni (kodovani, konce radku, BOM) */
} TxStats;
void tx_count(const char *s, gsize len, const TxEncoding *enc, TxLineEnd le, TxStats *st);

/* Jazyk podle jmena souboru a obsahu (shebang, vlastni pravidla, pak GtkSourceView); NULL = prosty text */
GtkSourceLanguage *tx_guess_language(GtkSourceLanguageManager *lm, const char *filename, const char *head, gsize len);

/* Osnova dokumentu: nadpisy Markdownu, funkce a tridy kodu */
typedef struct {
    int line;       /* od 0 */
    int level;      /* odsazeni v nabidce */
    char *title;
} TxSymbol;
gboolean tx_outline_supported(const char *lang_id);
GPtrArray *tx_outline(const char *lang_id, const char *s, gsize len);   /* pole TxSymbol*, uvolni g_ptr_array_unref */

/* Odsazeni tabulatory? (vic radku zacina tabulatorem nez mezerami) */
gboolean tx_detect_tabs(const char *s, gsize len);

/* Nedavne soubory: path na zacatek, bez duplicit, nejvys max polozek (vraci novy seznam, puvodni uvolni) */
char **tx_recent_add(char **list, const char *path, int max);
char **tx_recent_remove(char **list, const char *path);

#endif
