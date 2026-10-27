/*
 * LuxOS Textovy editor - testy logiky bez okna (kodovani, konce radku, pocty, jazyk, osnova, nedavne soubory).
 *   gcc -o test-core tests/test-core.c files/text-core.c $(pkg-config --cflags --libs gtksourceview-4) && ./test-core
 */
#include "../files/text-core.h"
#include <string.h>

/* ceska veta "Prilis zlutoucky kun upel dabelske ody." v UTF-8 */
static const char *CZ = "P\xc5\x99\xc3\xadli\xc5\xa1 \xc5\xbelu\xc5\xa5ou\xc4\x8dk\xc3\xbd k\xc5\xaf\xc5\x88 "
                        "\xc3\xbap\xc4\x9bl \xc4\x8f\xc3\xa1\x62\x65lsk\xc3\xa9 \xc3\xb3\x64y.";

static char *conv(const char *utf8, const char *to, gsize *len)
{
    char *r = g_convert(utf8, -1, to, "UTF-8", NULL, len, NULL);
    g_assert_nonnull(r);
    return r;
}

static void roundtrip(const char *text, const char *enc_id, const char *lang)
{
    const TxEncoding *e = tx_encoding_find(enc_id);
    g_assert_nonnull(e);
    gsize n = 0;
    GError *err = NULL;
    char *bytes = tx_encode(text, strlen(text), e, TX_LF, &n, &err);
    g_assert_no_error(err);
    const TxEncoding *d = tx_detect_encoding(bytes, n, lang);
    g_assert_nonnull(d);
    g_assert_cmpstr(d->id, ==, enc_id);
    gsize ul = 0;
    char *u = tx_decode(bytes, n, d, &ul, &err);
    g_assert_no_error(err);
    g_assert_cmpstr(u, ==, text);
    /* znovu ulozit = stejne bajty */
    gsize n2 = 0;
    char *again = tx_encode(u, ul, d, TX_LF, &n2, &err);
    g_assert_cmpuint(n2, ==, n);
    g_assert_true(memcmp(again, bytes, n) == 0);
    g_free(again);
    g_free(u);
    g_free(bytes);
}

static void test_encoding_cp1250(void)
{
    char *t = g_strdup_printf("%s\nČeská republika, Šumava, Ťapka\n", CZ);
    roundtrip(t, "WINDOWS-1250", "cs");
    /* i s anglickym prostredim (t s hackem = 0x9D ve Windows-1252 neexistuje) */
    roundtrip(t, "WINDOWS-1250", "en");
    g_free(t);
}

static void test_encoding_latin2(void)
{
    /* ISO 8859-2: s, z, t s hackem jsou 0xB9 0xBE 0xBB (ve Windows-1250 a s ogonkem, l s hackem, >>) */
    roundtrip("Šťastný žák, šťovík a ťuhýk.\n", "ISO-8859-2", "cs");
}

static void test_encoding_cp1252(void)
{
    roundtrip("Grüße aus Köln – Äpfel für 5 €\n", "WINDOWS-1252", "de");
}

static void test_encoding_cp1251(void)
{
    roundtrip("Привіт, як справи? Їжак і ґанок.\n", "WINDOWS-1251", "uk");
    roundtrip("Привіт, як справи? Їжак і ґанок.\n", "WINDOWS-1251", "cs");
}

static void test_encoding_utf8_and_bom(void)
{
    roundtrip(CZ, "UTF-8", "cs");
    roundtrip("plain ascii\n", "UTF-8", "en");
    roundtrip(CZ, "UTF-8-BOM", "cs");
    /* BOM se v textu neobjevi */
    gsize n;
    char *b = tx_encode("abc", 3, tx_encoding_find("UTF-8-BOM"), TX_LF, &n, NULL);
    g_assert_cmpuint(n, ==, 6);
    char *u = tx_decode(b, n, tx_detect_encoding(b, n, "cs"), NULL, NULL);
    g_assert_cmpstr(u, ==, "abc");
    g_free(u);
    g_free(b);
}

static void test_encoding_utf16(void)
{
    roundtrip(CZ, "UTF-16LE", "cs");
    roundtrip(CZ, "UTF-16BE", "cs");
    /* bez BOM: podle nulovych bajtu */
    gsize n;
    char *b = conv("Hello world, this is UTF-16 without BOM\n", "UTF-16LE", &n);
    g_assert_cmpstr(tx_detect_encoding(b, n, "en")->id, ==, "UTF-16LE");
    g_free(b);
    b = conv("Hello world, this is UTF-16 without BOM\n", "UTF-16BE", &n);
    g_assert_cmpstr(tx_detect_encoding(b, n, "en")->id, ==, "UTF-16BE");
    g_free(b);
}

static void test_binary(void)
{
    const char bin[] = {0x7f, 'E', 'L', 'F', 2, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0x3e, 0, 1, 0, 0, 0};
    g_assert_null(tx_detect_encoding(bin, sizeof bin, "cs"));
}

static void test_unencodable(void)
{
    GError *err = NULL;
    gsize n;
    char *b = tx_encode("emoji 😀", strlen("emoji 😀"), tx_encoding_find("WINDOWS-1250"), TX_LF, &n, &err);
    g_assert_null(b);
    g_assert_nonnull(err);
    g_error_free(err);
}

static void test_line_endings(void)
{
    const char *crlf = "a\r\nb\r\nc\r\n", *cr = "a\rb\rc", *lf = "a\nb\n", *mixed = "a\r\nb\r\nc\nd\r\n";
    g_assert_cmpint(tx_detect_line_ending(crlf, strlen(crlf)), ==, TX_CRLF);
    g_assert_cmpint(tx_detect_line_ending(cr, strlen(cr)), ==, TX_CR);
    g_assert_cmpint(tx_detect_line_ending(lf, strlen(lf)), ==, TX_LF);
    g_assert_cmpint(tx_detect_line_ending("abc", 3), ==, TX_LF);
    g_assert_cmpint(tx_detect_line_ending(mixed, strlen(mixed)), ==, TX_CRLF);
    g_assert_true(tx_has_mixed_line_endings(mixed, strlen(mixed)));
    g_assert_false(tx_has_mixed_line_endings(crlf, strlen(crlf)));
    /* nacteni (normalizace na LF) a ulozeni vrati puvodni bajty */
    const char *files[] = {crlf, cr, lf};
    for (int i = 0; i < 3; i++) {
        gsize n, m;
        TxLineEnd le = tx_detect_line_ending(files[i], strlen(files[i]));
        char *norm = tx_normalize_newlines(files[i], strlen(files[i]), &n);
        g_assert_null(strchr(norm, '\r'));
        char *out = tx_encode(norm, n, tx_encoding_utf8(), le, &m, NULL);
        g_assert_cmpuint(m, ==, strlen(files[i]));
        g_assert_true(memcmp(out, files[i], m) == 0);
        g_free(out);
        g_free(norm);
    }
    /* CP1250 + CRLF */
    gsize n, m;
    char *b = tx_encode("řádek\nšest\n", strlen("řádek\nšest\n"), tx_encoding_find("WINDOWS-1250"), TX_CRLF, &n, NULL);
    g_assert_cmpuint(n, ==, 13);
    g_assert_true(b[5] == '\r' && b[6] == '\n');
    char *u = tx_decode(b, n, tx_encoding_find("WINDOWS-1250"), &m, NULL);
    g_assert_cmpint(tx_detect_line_ending(u, m), ==, TX_CRLF);
    g_free(u);
    g_free(b);
    g_assert_cmpint(tx_line_ending_from_name("crlf"), ==, TX_CRLF);
    g_assert_cmpstr(tx_line_ending_name(TX_CR), ==, "CR");
}

static void test_count(void)
{
    TxStats st;
    tx_count("", 0, NULL, TX_LF, &st);
    g_assert_cmpint(st.lines, ==, 0);
    g_assert_cmpint(st.words, ==, 0);
    tx_count(CZ, strlen(CZ), NULL, TX_LF, &st);
    g_assert_cmpint(st.lines, ==, 1);
    g_assert_cmpint(st.words, ==, 6);
    g_assert_cmpint(st.chars, ==, 39);
    g_assert_cmpint(st.bytes, ==, (gint64)strlen(CZ));
    const char *t = "Hello, world!\nDon't stop - 42 times.\n";
    tx_count(t, strlen(t), NULL, TX_LF, &st);
    g_assert_cmpint(st.lines, ==, 3);
    g_assert_cmpint(st.words, ==, 6);
    g_assert_cmpint(st.chars, ==, (gint64)strlen(t) - 2);
    tx_count(t, strlen(t), NULL, TX_CRLF, &st);
    g_assert_cmpint(st.bytes, ==, (gint64)strlen(t) + 2);
    /* velikost v jinem kodovani = skutecna velikost po ulozeni */
    const char *encs[] = {"WINDOWS-1250", "UTF-16LE", "UTF-8-BOM", "UTF-8"};
    for (int i = 0; i < 4; i++) {
        const TxEncoding *e = tx_encoding_find(encs[i]);
        for (int le = 0; le < 3; le++) {
            gsize n;
            char *b = tx_encode(CZ, strlen(CZ), e, le, &n, NULL);
            char *two = g_strdup_printf("%s\n%s\n", CZ, CZ);
            g_free(b);
            b = tx_encode(two, strlen(two), e, le, &n, NULL);
            tx_count(two, strlen(two), e, le, &st);
            g_assert_cmpint(st.bytes, ==, (gint64)n);
            g_free(b);
            g_free(two);
        }
    }
    /* cinstina, japonstina */
    tx_count("日本語のテキスト", strlen("日本語のテキスト"), NULL, TX_LF, &st);
    g_assert_cmpint(st.chars, ==, 8);
    g_assert_cmpint(st.words, ==, 1);
}

static void check_lang(GtkSourceLanguageManager *lm, const char *name, const char *head, const char *want)
{
    GtkSourceLanguage *l = tx_guess_language(lm, name, head, head ? strlen(head) : 0);
    const char *got = l ? gtk_source_language_get_id(l) : NULL;
    if (g_strcmp0(got, want)) g_error("%s: language %s, expected %s", name ? name : head, got, want);
}

static void test_language(void)
{
    GtkSourceLanguageManager *lm = gtk_source_language_manager_new();
    const char *dir = g_getenv("LUXOS_TEXT_LANG_DIR");
    if (dir) {
        const char *const *old = gtk_source_language_manager_get_search_path(lm);
        GPtrArray *p = g_ptr_array_new();
        g_ptr_array_add(p, (char *)dir);
        for (int i = 0; old[i]; i++) g_ptr_array_add(p, (char *)old[i]);
        g_ptr_array_add(p, NULL);
        gtk_source_language_manager_set_search_path(lm, (char **)p->pdata);
        g_ptr_array_free(p, TRUE);
    }
    check_lang(lm, "notes.txt", "Hello", NULL);
    check_lang(lm, "script.py", "import os\n", "python3");
    check_lang(lm, "run", "#!/usr/bin/env python3\nprint(1)\n", "python3");
    check_lang(lm, "run", "#!/bin/bash\necho hi\n", "sh");
    check_lang(lm, "tool", "#!/usr/bin/lsh\nls\n", "sh");
    check_lang(lm, "PKGBUILD", "pkgname=x\n", "sh");
    check_lang(lm, "README.md", "# Title\n", "markdown");
    check_lang(lm, "main.c", "int main(void) {}\n", "c");
    check_lang(lm, "data.json", "{}", "json");
    check_lang(lm, "app.desktop", "[Desktop Entry]\n", "desktop");
    check_lang(lm, "Containerfile", "FROM x\n", "docker");
    check_lang(lm, "luxos.service", "[Unit]\n", "ini");
    if (dir) {
        check_lang(lm, "hello.lsl", "print \"hi\"\n", "lsl");
        check_lang(lm, "tool", "#!/usr/bin/env lsl\nprint 1\n", "lsl");
    }
    g_object_unref(lm);
}

static void check_outline(const char *lang, const char *text, const char *want)
{
    GPtrArray *a = tx_outline(lang, text, strlen(text));
    GString *s = g_string_new(NULL);
    for (guint i = 0; i < a->len; i++) {
        TxSymbol *y = a->pdata[i];
        g_string_append_printf(s, "%s%d:%d:%s", i ? "|" : "", y->line, y->level, y->title);
    }
    if (strcmp(s->str, want)) g_error("outline %s: got '%s', expected '%s'", lang, s->str, want);
    g_string_free(s, TRUE);
    g_ptr_array_unref(a);
}

static void test_outline(void)
{
    check_outline("markdown", "# Source Code\ntext\n## Build\n```\n# not heading\n```\nSetext\n===\n", "0:0:Source Code|2:1:Build|6:0:Setext");
    check_outline("python3", "import os\nclass A:\n    def run(self):\n        pass\nasync def main():\n    pass\n",
                  "1:0:A|2:1:run|4:0:main");
    check_outline("c", "#include <x.h>\nstatic int add(int a,\n               int b)\n{\n    return a + b;\n}\n"
                       "int proto(void);\nint main(void) {\n    if (x) {\n    }\n}\n",
                  "1:0:add|7:0:main");
    check_outline("sh", "foo() {\n  :\n}\nfunction bar {\n}\nbaz () {\n}\n", "0:0:foo|3:0:bar|5:0:baz");
    check_outline("lsl", "function motor(power):\n    return power\nend\nclass Car:\nend\n", "0:0:motor|3:0:Car");
    check_outline("ini", "[Unit]\nA=1\n[Service]\n", "0:0:Unit|2:0:Service");
    check_outline("js", "export function a() {}\nclass B {}\n", "0:0:a|1:0:B");
    g_assert_false(tx_outline_supported(NULL));
    g_assert_false(tx_outline_supported("json"));
    g_assert_true(tx_outline_supported("markdown"));
    g_assert_true(tx_outline_supported("python3"));
}

static void test_tabs(void)
{
    g_assert_true(tx_detect_tabs("a\n\tb\n\tc\n  d\n", 13));
    g_assert_false(tx_detect_tabs("a\n    b\n    c\n", 15));
}

static void test_recent(void)
{
    char **l = NULL;
    l = tx_recent_add(l, "/a", 3);
    l = tx_recent_add(l, "/b", 3);
    l = tx_recent_add(l, "/c", 3);
    l = tx_recent_add(l, "/a", 3);
    g_assert_cmpuint(g_strv_length(l), ==, 3);
    g_assert_cmpstr(l[0], ==, "/a");
    g_assert_cmpstr(l[1], ==, "/c");
    g_assert_cmpstr(l[2], ==, "/b");
    l = tx_recent_add(l, "/d", 3);
    g_assert_cmpstr(l[0], ==, "/d");
    g_assert_cmpstr(l[2], ==, "/c");
    l = tx_recent_remove(l, "/a");
    g_assert_cmpuint(g_strv_length(l), ==, 2);
    g_assert_cmpstr(l[1], ==, "/c");
    g_strfreev(l);
}

int main(int argc, char **argv)
{
    g_test_init(&argc, &argv, NULL);
    g_test_add_func("/encoding/cp1250", test_encoding_cp1250);
    g_test_add_func("/encoding/latin2", test_encoding_latin2);
    g_test_add_func("/encoding/cp1252", test_encoding_cp1252);
    g_test_add_func("/encoding/cp1251", test_encoding_cp1251);
    g_test_add_func("/encoding/utf8-bom", test_encoding_utf8_and_bom);
    g_test_add_func("/encoding/utf16", test_encoding_utf16);
    g_test_add_func("/encoding/binary", test_binary);
    g_test_add_func("/encoding/unencodable", test_unencodable);
    g_test_add_func("/line-endings", test_line_endings);
    g_test_add_func("/count", test_count);
    g_test_add_func("/language", test_language);
    g_test_add_func("/outline", test_outline);
    g_test_add_func("/tabs", test_tabs);
    g_test_add_func("/recent", test_recent);
    return g_test_run();
}
