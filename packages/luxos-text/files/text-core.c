/*
 * LuxOS Textovy editor - logika bez okna: kodovani, konce radku, pocty, jazyk, osnova, nedavne soubory.
 */
#include "text-core.h"
#include <string.h>

/* ---------- kodovani ---------- */
const TxEncoding tx_encodings[] = {
    {"UTF-8", "UTF-8", NULL, "UTF-8", 0, 0},
    {"UTF-8-BOM", "UTF-8", NULL, "UTF-8 with BOM", 1, 0},
    {"UTF-16LE", "UTF-16LE", NULL, "UTF-16 LE", 1, 2},
    {"UTF-16BE", "UTF-16BE", NULL, "UTF-16 BE", 1, 2},
    {"WINDOWS-1250", "WINDOWS-1250", "Central European", "Windows-1250", 0, 1},
    {"ISO-8859-2", "ISO-8859-2", "Central European", "ISO 8859-2", 0, 1},
    {"WINDOWS-1252", "WINDOWS-1252", "Western", "Windows-1252", 0, 1},
    {"ISO-8859-1", "ISO-8859-1", "Western", "ISO 8859-1", 0, 1},
    {"ISO-8859-15", "ISO-8859-15", "Western", "ISO 8859-15", 0, 1},
    {"WINDOWS-1251", "WINDOWS-1251", "Cyrillic", "Windows-1251", 0, 1},
    {"KOI8-U", "KOI8-U", "Cyrillic", "KOI8-U", 0, 1},
    {"WINDOWS-1253", "WINDOWS-1253", "Greek", "Windows-1253", 0, 1},
    {"WINDOWS-1254", "WINDOWS-1254", "Turkish", "Windows-1254", 0, 1},
    {"WINDOWS-1257", "WINDOWS-1257", "Baltic", "Windows-1257", 0, 1},
    {"SHIFT_JIS", "SHIFT_JIS", "Japanese", "Shift JIS", 0, 0},
    {"GB18030", "GB18030", "Chinese Simplified", "GB 18030", 0, 0},
    {"EUC-KR", "EUC-KR", "Korean", "EUC-KR", 0, 0},
};
const int tx_n_encodings = G_N_ELEMENTS(tx_encodings);

const TxEncoding *tx_encoding_find(const char *id)
{
    if (!id) return NULL;
    for (int i = 0; i < tx_n_encodings; i++)
        if (!g_ascii_strcasecmp(tx_encodings[i].id, id)) return &tx_encodings[i];
    return NULL;
}

const TxEncoding *tx_encoding_utf8(void) { return &tx_encodings[0]; }

/* Pravdepodobnost textu v jednobajtovem kodovani: pismena mimo ASCII vedle pismen stejneho pisma (latinka
 * vedle ASCII pismen, azbuka vedle azbuky) +1, symboly a ridici znaky minus. */
static int is_cyrillic(gunichar c) { return c >= 0x400 && c <= 0x52f; }
static int is_ascii_alpha(gunichar c) { return c < 128 && g_ascii_isalpha(c); }

static long plausibility(const char *u, gsize len, int cyrillic)
{
    long score = 0;
    gunichar prev = ' ';
    const char *p = u, *end = u + len;
    while (p < end) {
        gunichar c = g_utf8_get_char(p);
        const char *n = g_utf8_next_char(p);
        gunichar next = n < end ? g_utf8_get_char(n) : ' ';
        if (c >= 0x80) {
            if (c < 0xa0) score -= 5;                         /* ridici znaky C1 */
            else if (g_unichar_isalpha(c)) {
                if (cyrillic) {
                    if (is_cyrillic(c) && (is_cyrillic(prev) || is_cyrillic(next))) score++;
                } else if (!is_cyrillic(c) && (is_ascii_alpha(prev) || is_ascii_alpha(next))) score++;
            } else if (c != 0xa0 && c != 0x2013 && c != 0x2014 && c != 0x201e && c != 0x201c &&
                       c != 0x201d && c != 0x2019 && c != 0x2018 && c != 0x20ac && c != 0xb0 && c != 0x2026)
                score--;                                       /* symboly (copyright, >>, hacek...) - bezne uvozovky ne */
        }
        prev = c;
        p = n;
    }
    return score;
}

/* Poradi kandidatu podle jazyka uzivatele (pri shode skore vyhrava prvni) */
static const char *const *single_byte_candidates(const char *lang)
{
    static const char *const ce[] = {"WINDOWS-1250", "ISO-8859-2", "WINDOWS-1252", "WINDOWS-1251", NULL};
    static const char *const cyr[] = {"WINDOWS-1251", "KOI8-U", "WINDOWS-1250", "WINDOWS-1252", NULL};
    static const char *const we[] = {"WINDOWS-1252", "WINDOWS-1250", "ISO-8859-2", "WINDOWS-1251", NULL};
    if (lang && (!strcmp(lang, "cs") || !strcmp(lang, "sk") || !strcmp(lang, "pl") || !strcmp(lang, "hu") ||
                 !strcmp(lang, "sl") || !strcmp(lang, "hr") || !strcmp(lang, "ro")))
        return ce;
    if (lang && (!strcmp(lang, "uk") || !strcmp(lang, "ru") || !strcmp(lang, "be") || !strcmp(lang, "bg") ||
                 !strcmp(lang, "sr")))
        return cyr;
    return we;
}

const TxEncoding *tx_detect_encoding(const char *data, gsize len, const char *lang)
{
    const guchar *d = (const guchar *)data;
    if (len >= 3 && d[0] == 0xef && d[1] == 0xbb && d[2] == 0xbf) return tx_encoding_find("UTF-8-BOM");
    if (len >= 2 && d[0] == 0xff && d[1] == 0xfe) return tx_encoding_find("UTF-16LE");
    if (len >= 2 && d[0] == 0xfe && d[1] == 0xff) return tx_encoding_find("UTF-16BE");
    /* UTF-16 bez BOM: nuly skoro jen na lichych (LE) nebo sudych (BE) pozicich */
    gsize zeros_even = 0, zeros_odd = 0, pairs = len / 2;
    gboolean has_zero = FALSE;
    for (gsize i = 0; i < len; i++)
        if (!d[i]) { has_zero = TRUE; if (i & 1) zeros_odd++; else zeros_even++; }
    if (has_zero && pairs >= 2) {
        if (zeros_odd * 10 > pairs * 4 && zeros_even * 20 < pairs) return tx_encoding_find("UTF-16LE");
        if (zeros_even * 10 > pairs * 4 && zeros_odd * 20 < pairs) return tx_encoding_find("UTF-16BE");
    }
    if (has_zero) return NULL;    /* binarni soubor */
    if (g_utf8_validate_len(data, len, NULL)) return tx_encoding_utf8();
    const char *const *cand = single_byte_candidates(lang);
    const TxEncoding *best = NULL;
    long best_score = G_MINLONG;
    for (int i = 0; cand[i]; i++) {
        const TxEncoding *e = tx_encoding_find(cand[i]);
        gsize ol = 0;
        char *u = g_convert(data, len, "UTF-8", e->iconv, NULL, &ol, NULL);
        if (!u) continue;    /* nedefinovany bajt (napr. 0x9D ve Windows-1252) */
        long s = plausibility(u, ol, !strcmp(e->region, "Cyrillic"));
        g_free(u);
        if (s > best_score) { best_score = s; best = e; }
    }
    /* Latin-1 umi kazdy bajt */
    return best ? best : tx_encoding_find("ISO-8859-1");
}

char *tx_decode(const char *data, gsize len, const TxEncoding *enc, gsize *out_len, GError **err)
{
    const guchar *d = (const guchar *)data;
    if (!enc) enc = tx_encoding_utf8();
    /* BOM se nezobrazuje */
    if (!strcmp(enc->iconv, "UTF-8") && len >= 3 && d[0] == 0xef && d[1] == 0xbb && d[2] == 0xbf) { data += 3; len -= 3; }
    else if (!strcmp(enc->id, "UTF-16LE") && len >= 2 && d[0] == 0xff && d[1] == 0xfe) { data += 2; len -= 2; }
    else if (!strcmp(enc->id, "UTF-16BE") && len >= 2 && d[0] == 0xfe && d[1] == 0xff) { data += 2; len -= 2; }
    if (!strcmp(enc->iconv, "UTF-8")) {
        const char *bad = NULL;
        if (!g_utf8_validate_len(data, len, &bad)) {
            g_set_error(err, G_CONVERT_ERROR, G_CONVERT_ERROR_ILLEGAL_SEQUENCE, "invalid UTF-8 at byte %ld",
                        (long)(bad - data));
            return NULL;
        }
        if (out_len) *out_len = len;
        return g_strndup(data, len);
    }
    gsize ol = 0;
    char *u = g_convert(data, len, "UTF-8", enc->iconv, NULL, &ol, err);
    if (u && memchr(u, 0, ol)) {   /* nulovy znak by text v GtkTextBufferu useknul */
        g_free(u);
        g_set_error(err, G_CONVERT_ERROR, G_CONVERT_ERROR_ILLEGAL_SEQUENCE, "NUL character");
        return NULL;
    }
    if (u && out_len) *out_len = ol;
    return u;
}

/* ---------- konce radku ---------- */
static void count_line_endings(const char *s, gsize len, gsize *lf, gsize *crlf, gsize *cr)
{
    *lf = *crlf = *cr = 0;
    for (gsize i = 0; i < len; i++) {
        if (s[i] == '\r') {
            if (i + 1 < len && s[i + 1] == '\n') { (*crlf)++; i++; }
            else (*cr)++;
        } else if (s[i] == '\n') (*lf)++;
    }
}

TxLineEnd tx_detect_line_ending(const char *s, gsize len)
{
    gsize lf, crlf, cr;
    count_line_endings(s, len, &lf, &crlf, &cr);
    if (crlf > lf && crlf >= cr) return TX_CRLF;
    if (cr > lf && cr > crlf) return TX_CR;
    return TX_LF;
}

gboolean tx_has_mixed_line_endings(const char *s, gsize len)
{
    gsize lf, crlf, cr;
    count_line_endings(s, len, &lf, &crlf, &cr);
    return (lf > 0) + (crlf > 0) + (cr > 0) > 1;
}

char *tx_normalize_newlines(const char *s, gsize len, gsize *out_len)
{
    char *o = g_malloc(len + 1);
    gsize j = 0;
    for (gsize i = 0; i < len; i++) {
        if (s[i] == '\r') {
            o[j++] = '\n';
            if (i + 1 < len && s[i + 1] == '\n') i++;
        } else o[j++] = s[i];
    }
    o[j] = 0;
    if (out_len) *out_len = j;
    return o;
}

const char *tx_line_ending_name(TxLineEnd le)
{
    return le == TX_CRLF ? "CRLF" : le == TX_CR ? "CR" : "LF";
}

int tx_line_ending_from_name(const char *name)
{
    if (!name) return -1;
    if (!g_ascii_strcasecmp(name, "LF")) return TX_LF;
    if (!g_ascii_strcasecmp(name, "CRLF")) return TX_CRLF;
    if (!g_ascii_strcasecmp(name, "CR")) return TX_CR;
    return -1;
}

char *tx_encode(const char *s, gsize len, const TxEncoding *enc, TxLineEnd le, gsize *out_len, GError **err)
{
    if (!enc) enc = tx_encoding_utf8();
    GString *t = g_string_sized_new(len + 16);
    for (gsize i = 0; i < len; i++) {
        if (s[i] == '\n' && le == TX_CRLF) g_string_append(t, "\r\n");
        else if (s[i] == '\n' && le == TX_CR) g_string_append_c(t, '\r');
        else g_string_append_c(t, s[i]);
    }
    GString *o;
    if (!strcmp(enc->iconv, "UTF-8")) {
        o = g_string_sized_new(t->len + 3);
        if (enc->bom) g_string_append(o, "\xef\xbb\xbf");
        g_string_append_len(o, t->str, t->len);
    } else {
        gsize ol = 0;
        char *c = g_convert(t->str, t->len, enc->iconv, "UTF-8", NULL, &ol, err);
        if (!c) { g_string_free(t, TRUE); return NULL; }
        o = g_string_sized_new(ol + 2);
        if (enc->bom && !strcmp(enc->id, "UTF-16LE")) g_string_append_len(o, "\xff\xfe", 2);
        else if (enc->bom && !strcmp(enc->id, "UTF-16BE")) g_string_append_len(o, "\xfe\xff", 2);
        g_string_append_len(o, c, ol);
        g_free(c);
    }
    g_string_free(t, TRUE);
    if (out_len) *out_len = o->len;
    return g_string_free(o, FALSE);
}

/* ---------- pocty ---------- */
static gboolean word_char(gunichar c)
{
    if (c < 128) return g_ascii_isalnum(c) || c == '_';
    switch (g_unichar_type(c)) {
    case G_UNICODE_LOWERCASE_LETTER: case G_UNICODE_UPPERCASE_LETTER: case G_UNICODE_TITLECASE_LETTER:
    case G_UNICODE_MODIFIER_LETTER: case G_UNICODE_OTHER_LETTER: case G_UNICODE_DECIMAL_NUMBER:
    case G_UNICODE_LETTER_NUMBER: case G_UNICODE_OTHER_NUMBER: case G_UNICODE_NON_SPACING_MARK:
    case G_UNICODE_SPACING_MARK: case G_UNICODE_ENCLOSING_MARK: case G_UNICODE_CONNECT_PUNCTUATION:
        return TRUE;
    default:
        return FALSE;
    }
}

void tx_count(const char *s, gsize len, const TxEncoding *enc, TxLineEnd le, TxStats *st)
{
    gint64 lf = 0, chars = 0, words = 0, astral = 0;
    gboolean in_word = FALSE;
    gunichar prev = 0;
    const char *p = s, *end = s + len;
    while (p < end) {
        guchar b = (guchar)*p;
        gunichar c;
        if (b < 0x80) { c = b; p++; }
        else { c = g_utf8_get_char(p); p = g_utf8_next_char(p); }
        if (c == '\n') { lf++; in_word = FALSE; prev = c; continue; }
        chars++;
        if (c > 0xffff) astral++;
        if (word_char(c)) {
            if (!in_word) words++;
            in_word = TRUE;
        } else if ((c == '\'' || c == 0x2019) && in_word && p < end) {
            /* apostrof uvnitr slova (don't) slovo nerozdeli */
            gunichar n = g_utf8_get_char(p);
            in_word = word_char(n) && word_char(prev);
            if (in_word) { prev = c; continue; }
        } else in_word = FALSE;
        prev = c;
    }
    st->lines = len ? lf + 1 : 0;
    st->chars = chars;
    st->words = words;
    if (!enc) enc = tx_encoding_utf8();
    gint64 nl_bytes = le == TX_CRLF ? 2 : 1;
    if (enc->unit == 2) st->bytes = 2 + (chars + astral) * 2 + lf * nl_bytes * 2;
    else if (enc->unit == 1) st->bytes = chars + lf * nl_bytes;
    else st->bytes = (gint64)len - lf + lf * nl_bytes + (enc->bom ? 3 : 0);   /* UTF-8, odhad u CJK */
}

/* ---------- jazyk ---------- */
static const char *shebang_language(const char *head, gsize len)
{
    if (len < 3 || head[0] != '#' || head[1] != '!') return NULL;
    gsize e = 2;
    while (e < len && head[e] != '\n' && head[e] != '\r') e++;
    char *line = g_strndup(head + 2, e - 2);
    char **parts = g_strsplit_set(g_strstrip(line), " \t", -1);
    const char *res = NULL;
    char *prog = NULL;
    for (int i = 0; parts[i]; i++) {
        if (!*parts[i]) continue;
        char *base = g_path_get_basename(parts[i]);
        if (!strcmp(base, "env") || base[0] == '-') { g_free(base); continue; }
        prog = base;
        break;
    }
    if (prog) {
        /* python3.12 -> python, bash5 -> bash */
        gsize n = strlen(prog);
        while (n && (g_ascii_isdigit(prog[n - 1]) || prog[n - 1] == '.')) prog[--n] = 0;
        static const char *const map[][2] = {
            {"python", "python3"}, {"bash", "sh"}, {"sh", "sh"}, {"dash", "sh"}, {"zsh", "sh"}, {"ksh", "sh"},
            {"lsh", "sh"}, {"fish", "fish"}, {"node", "js"}, {"nodejs", "js"}, {"perl", "perl"},
            {"ruby", "ruby"}, {"lua", "lua"}, {"php", "php"}, {"lsl", "lsl"}, {"awk", "awk"}, {"gawk", "awk"},
            {"tclsh", "tcl"}, {"make", "makefile"}, {"Rscript", "r"},
        };
        for (guint i = 0; i < G_N_ELEMENTS(map); i++)
            if (!strcmp(prog, map[i][0])) { res = map[i][1]; break; }
    }
    g_free(prog);
    g_strfreev(parts);
    g_free(line);
    return res;
}

static const char *name_language(const char *base)
{
    static const char *const names[][2] = {
        {"PKGBUILD", "sh"}, {".lshrc", "sh"}, {"lshrc", "sh"}, {".zshrc", "sh"}, {".bash_aliases", "sh"},
        {".bash_logout", "sh"}, {".xinitrc", "sh"}, {".xprofile", "sh"}, {"Containerfile", "docker"},
        {"Dockerfile", "docker"}, {"CMakeLists.txt", "cmake"}, {"Makefile", "makefile"}, {"GNUmakefile", "makefile"},
        {"makefile", "makefile"}, {"meson.build", "meson"}, {".gitconfig", "ini"}, {"CHANGELOG.md", "markdown"},
    };
    for (guint i = 0; i < G_N_ELEMENTS(names); i++)
        if (!strcmp(base, names[i][0])) return names[i][1];
    const char *dot = strrchr(base, '.');
    if (!dot) return NULL;
    static const char *const ext[][2] = {
        {".lsl", "lsl"}, {".install", "sh"}, {".hook", "ini"}, {".service", "ini"}, {".timer", "ini"},
        {".socket", "ini"}, {".mount", "ini"}, {".target", "ini"}, {".path", "ini"}, {".conf", "ini"},
        {".rasi", "css"}, {".tsv", "csv"}, {".mjs", "js"}, {".cjs", "js"}, {".jsonc", "json"},
    };
    for (guint i = 0; i < G_N_ELEMENTS(ext); i++)
        if (!strcmp(dot, ext[i][0])) return ext[i][1];
    return NULL;
}

GtkSourceLanguage *tx_guess_language(GtkSourceLanguageManager *lm, const char *filename, const char *head, gsize len)
{
    GtkSourceLanguage *l = NULL;
    const char *id = head ? shebang_language(head, len) : NULL;
    if (id && (l = gtk_source_language_manager_get_language(lm, id))) return l;
    if (filename) {
        char *base = g_path_get_basename(filename);
        id = name_language(base);
        g_free(base);
        if (id && (l = gtk_source_language_manager_get_language(lm, id))) return l;
    }
    gboolean uncertain = FALSE;
    char *ct = g_content_type_guess(filename, (const guchar *)head, head ? MIN(len, 4096) : 0, &uncertain);
    if (ct && (!strcmp(ct, "text/plain") || !strcmp(ct, "application/octet-stream"))) g_clear_pointer(&ct, g_free);
    l = gtk_source_language_manager_guess_language(lm, filename, ct);
    g_free(ct);
    /* python.lang je Python 2 - pro *.py vzdy Python 3 */
    if (l && !strcmp(gtk_source_language_get_id(l), "python")) {
        GtkSourceLanguage *p3 = gtk_source_language_manager_get_language(lm, "python3");
        if (p3) l = p3;
    }
    return l;
}

/* ---------- osnova ---------- */
typedef struct {
    const char *ids;      /* jazyky oddelene "|" */
    const char *pattern;  /* skupina "name" = titulek, "ind" = odsazeni (uroven) */
} OutlineRule;

static const OutlineRule outline_rules[] = {
    {"|python3|python|", "^(?<ind>[ \\t]*)(?:async[ \\t]+)?(?:def|class)[ \\t]+(?<name>\\w+)"},
    {"|lsl|", "^(?<ind>[ \\t]*)(?:function|class)[ \\t]+(?<name>\\w+)"},
    {"|c|chdr|cpp|cpphdr|objc|cuda|glsl|opencl|",
     "^(?<ind>)(?!(?:if|for|while|switch|return|else|do|typedef|struct|enum|union|case|goto)\\b)"
     "[A-Za-z_][\\w \\t\\*&:<>,]*?\\b(?<name>[A-Za-z_][\\w:~]*)[ \\t]*\\([^;\\n]*$"},
    {"|js|typescript|jsx|typescript-jsx|",
     "^(?<ind>[ \\t]*)(?:export[ \\t]+)?(?:default[ \\t]+)?(?:async[ \\t]+)?"
     "(?:function\\*?[ \\t]+(?<name>[\\w$]+)|class[ \\t]+(?<name2>[\\w$]+))"},
    {"|sh|fish|", "^(?<ind>[ \\t]*)(?:function[ \\t]+(?<name>[A-Za-z_][\\w:.-]*)|(?<name2>[A-Za-z_][\\w:.-]*)[ \\t]*\\(\\))"},
    {"|rust|", "^(?<ind>[ \\t]*)(?:pub(?:\\([^)]*\\))?[ \\t]+)?(?:async[ \\t]+)?(?:fn|struct|enum|trait|impl|mod)[ \\t]+(?<name>[\\w<>]+)"},
    {"|go|", "^(?<ind>)func[ \\t]+(?:\\([^)]*\\)[ \\t]*)?(?<name>\\w+)"},
    {"|java|csharp|kotlin|scala|vala|",
     "^(?<ind>[ \\t]*)(?:(?:public|private|protected|internal|static|abstract|final|sealed|override|virtual|async|open|data)[ \\t]+)*"
     "(?:class|interface|enum|struct|object|fun|record)[ \\t]+(?<name>\\w+)"},
    {"|ruby|", "^(?<ind>[ \\t]*)(?:def|class|module)[ \\t]+(?<name>[\\w.?!]+)"},
    {"|lua|", "^(?<ind>[ \\t]*)(?:local[ \\t]+)?function[ \\t]+(?<name>[\\w.:]+)"},
    {"|perl|", "^(?<ind>[ \\t]*)sub[ \\t]+(?<name>\\w+)"},
    {"|php|", "^(?<ind>[ \\t]*)(?:(?:public|private|protected|static|abstract|final)[ \\t]+)*(?:function|class)[ \\t]+(?<name>\\w+)"},
    {"|ini|desktop|toml|", "^(?<ind>)\\[(?<name>[^\\]\\n]+)\\]"},
    {"|makefile|", "^(?<ind>)(?<name>[A-Za-z0-9_./%-]+)[ \\t]*::?(?!=)"},
    {"|latex|", "^(?<ind>[ \\t]*)\\\\(?:part|chapter|section|subsection|subsubsection)\\*?\\{(?<name>[^}\\n]+)\\}"},
    {"|html|xml|", "<h[1-6][^>]*>(?<ind>)(?<name>[^<\\n]+)</h[1-6]>"},
    {"|css|scss|less|", "^(?<ind>)(?<name>[^\\s@{}/][^{}\\n;]*?)[ \\t]*\\{"},
    {"|yaml|", "^(?<ind>)(?<name>[A-Za-z_][\\w.-]*)[ \\t]*:(?:[ \\t]|$)"},
};

static const OutlineRule *outline_rule(const char *lang_id)
{
    if (!lang_id) return NULL;
    char *key = g_strdup_printf("|%s|", lang_id);
    const OutlineRule *r = NULL;
    for (guint i = 0; i < G_N_ELEMENTS(outline_rules) && !r; i++)
        if (strstr(outline_rules[i].ids, key)) r = &outline_rules[i];
    g_free(key);
    return r;
}

gboolean tx_outline_supported(const char *lang_id)
{
    return lang_id && (!strcmp(lang_id, "markdown") || outline_rule(lang_id));
}

static void symbol_free(gpointer p)
{
    TxSymbol *s = p;
    g_free(s->title);
    g_free(s);
}

static void add_symbol(GPtrArray *a, int line, int level, const char *title, gssize n)
{
    TxSymbol *s = g_new0(TxSymbol, 1);
    s->line = line;
    s->level = level;
    s->title = g_strstrip(n < 0 ? g_strdup(title) : g_strndup(title, n));
    g_ptr_array_add(a, s);
}

#define MAX_SYMBOLS 5000

static GPtrArray *outline_markdown(const char *s, gsize len)
{
    GPtrArray *a = g_ptr_array_new_with_free_func(symbol_free);
    gboolean fence = FALSE;
    int line = 0;
    const char *p = s, *end = s + len;
    while (p < end && a->len < MAX_SYMBOLS) {
        const char *e = memchr(p, '\n', end - p);
        if (!e) e = end;
        if (e - p >= 3 && (!strncmp(p, "```", 3) || !strncmp(p, "~~~", 3))) fence = !fence;
        else if (!fence && *p == '#') {
            int lvl = 0;
            while (p + lvl < e && p[lvl] == '#') lvl++;
            if (lvl <= 6 && p + lvl < e && (p[lvl] == ' ' || p[lvl] == '\t')) {
                const char *t = p + lvl, *te = e;
                while (te > t && (te[-1] == '#' || te[-1] == ' ' || te[-1] == '\t' || te[-1] == '\r')) te--;
                if (te > t) add_symbol(a, line, lvl - 1, t, te - t);
            }
        } else if (!fence && line > 0 && e > p && (*p == '=' || *p == '-')) {
            /* nadpis podtrzeny === nebo --- (Setext) pod neprazdnym radkem */
            const char *q = p;
            while (q < e && *q == *p) q++;
            while (q < e && (*q == ' ' || *q == '\r')) q++;
            const char *prev_end = p - 1, *prev = prev_end;
            while (prev > s && prev[-1] != '\n') prev--;
            if (q == e && e - p >= 2 && prev_end > prev && prev[0] != '#' &&
                !(a->len && ((TxSymbol *)a->pdata[a->len - 1])->line == line - 1))
                add_symbol(a, line - 1, *p == '=' ? 0 : 1, prev, prev_end - prev);
        }
        line++;
        p = e + 1;
    }
    return a;
}

GPtrArray *tx_outline(const char *lang_id, const char *s, gsize len)
{
    if (lang_id && !strcmp(lang_id, "markdown")) return outline_markdown(s, len);
    GPtrArray *a = g_ptr_array_new_with_free_func(symbol_free);
    const OutlineRule *r = outline_rule(lang_id);
    if (!r) return a;
    /* prelozeny vyraz se pamatuje pro kazde pravidlo */
    static GRegex *cache[G_N_ELEMENTS(outline_rules)];
    int idx = r - outline_rules;
    if (!cache[idx]) {
        GError *e = NULL;
        cache[idx] = g_regex_new(r->pattern, G_REGEX_MULTILINE | G_REGEX_OPTIMIZE | G_REGEX_DUPNAMES, 0, &e);
        if (!cache[idx]) {
            g_warning("outline regex %s: %s", r->ids, e->message);
            g_error_free(e);
            return a;
        }
    }
    GMatchInfo *mi = NULL;
    int line = 0;
    gssize counted = 0;
    gboolean is_c = strstr(r->ids, "|chdr|") != NULL;
    g_regex_match_full(cache[idx], s, len, 0, 0, &mi, NULL);
    while (g_match_info_matches(mi) && a->len < MAX_SYMBOLS) {
        int ms = 0, me = 0, ns = -1, ne = -1, is = -1, ie = -1;
        g_match_info_fetch_pos(mi, 0, &ms, &me);
        if (!g_match_info_fetch_named_pos(mi, "name", &ns, &ne) || ns < 0)
            g_match_info_fetch_named_pos(mi, "name2", &ns, &ne);
        g_match_info_fetch_named_pos(mi, "ind", &is, &ie);
        for (; counted < ms; counted++)
            if (s[counted] == '\n') line++;
        if (ns >= 0 && ne > ns) {
            int level = 0;
            for (int i = is; i >= 0 && i < ie; i++) level += s[i] == '\t' ? 4 : 1;
            /* C: deklarace funkce (konci strednikem na dalsich radcich) se preskoci - definice ma "{" */
            gboolean ok = TRUE;
            if (is_c) {
                /* za jmenem prvni "{" nebo ";"; mezi posledni ")" a "{" jen mezery = definice funkce */
                const char *b = s + ne, *close = NULL;
                while (b < s + len && *b != '{' && *b != ';' && b - (s + ne) < 600) {
                    if (*b == ')') close = b;
                    b++;
                }
                ok = b < s + len && *b == '{' && close;
                for (const char *q = close ? close + 1 : b; ok && q < b; q++)
                    if (!g_ascii_isspace(*q)) ok = FALSE;
            }
            if (ok) add_symbol(a, line, level / 4, s + ns, ne - ns);
        }
        g_match_info_next(mi, NULL);
    }
    g_match_info_free(mi);
    return a;
}

gboolean tx_detect_tabs(const char *s, gsize len)
{
    int tabs = 0, spaces = 0;
    const char *p = s, *end = s + len;
    int n = 0;
    while (p < end && n < 2000) {
        if (*p == '\t') tabs++;
        else if (p + 1 < end && p[0] == ' ' && p[1] == ' ') spaces++;
        const char *e = memchr(p, '\n', end - p);
        if (!e) break;
        p = e + 1;
        n++;
    }
    return tabs > spaces;
}

/* ---------- nedavne soubory ---------- */
char **tx_recent_add(char **list, const char *path, int max)
{
    GPtrArray *a = g_ptr_array_new();
    g_ptr_array_add(a, g_strdup(path));
    for (int i = 0; list && list[i] && (int)a->len < max; i++)
        if (strcmp(list[i], path)) g_ptr_array_add(a, g_strdup(list[i]));
    g_ptr_array_add(a, NULL);
    g_strfreev(list);
    return (char **)g_ptr_array_free(a, FALSE);
}

char **tx_recent_remove(char **list, const char *path)
{
    GPtrArray *a = g_ptr_array_new();
    for (int i = 0; list && list[i]; i++)
        if (strcmp(list[i], path)) g_ptr_array_add(a, g_strdup(list[i]));
    g_ptr_array_add(a, NULL);
    g_strfreev(list);
    return (char **)g_ptr_array_free(a, FALSE);
}
