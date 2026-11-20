/* wlt-frames - kontrola snimku PPM (P6) z grim -t ppm nebo QMP screendump
 *   wlt-frames stat FILE..        rozmery, pocet barev, podil necerne plochy
 *   wlt-frames diff A B           podil zmenenych bloku
 *   wlt-frames check [volby] DIR|FILE..   detektor blikani; exit 1 = nalez
 *
 * Detektor: snimky se zmensi na mrizku bloku (prumer barvy), stejne po sobe jdouci snimky
 * se sloucí do behu (obrazovka se nezmenila). Na posloupnosti behu hlasi:
 *   black      snimek je skoro cely cerny
 *   transient  beh se lisi od predchoziho i nasledujiciho v blocich, kde se predchozi
 *              a nasledujici shoduji (problikl cerny, poloprekresleny nebo cizi obsah)
 *   regressed  beh se vratil ke starsimu stavu a hned pokracuje od predchoziho
 *              (obrazovka na okamzik ukazala starsi snimek)
 * transient a regressed jen u behu kratsich nez --max-run snimku: stav, ktery na obrazovce vydrzi,
 * je skutecny (napr. okno na konci tazeni, kdyz se pak tahne zpet), ne probliknuti.
 * Volby: --block N (16) --thr T (12, rozdil barvy 0-255) --min F (0.02, podil bloku)
 *        --same F (0.005) --back K (8 behu) --max-run N (2) --allow-black */
#define _DEFAULT_SOURCE
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

struct img {
	int w, h;
	unsigned char *px;
};

struct frame {
	char *name;
	float *blk;
	double black;
};

static int block = 16, allow_black;
static double thr = 12, min_frac = 0.02, same_frac = 0.005;
static int back = 8, max_run = 2, bw, bh;

static int ppm_int(FILE *f)
{
	int c, v = 0;
	while ((c = fgetc(f)) != EOF) {
		if (c == '#')
			while ((c = fgetc(f)) != EOF && c != '\n')
				;
		else if (c >= '0' && c <= '9')
			break;
	}
	if (c == EOF)
		return -1;
	do
		v = v * 10 + c - '0';
	while ((c = fgetc(f)) >= '0' && c <= '9');
	return v;
}

static int load(const char *path, struct img *im)
{
	FILE *f = fopen(path, "rb");
	if (!f) {
		perror(path);
		return -1;
	}
	char magic[2];
	int max;
	if (fread(magic, 1, 2, f) != 2 || magic[0] != 'P' || magic[1] != '6' ||
	    (im->w = ppm_int(f)) <= 0 || (im->h = ppm_int(f)) <= 0 || (max = ppm_int(f)) != 255) {
		fprintf(stderr, "%s: not an 8-bit P6 PPM\n", path);
		fclose(f);
		return -1;
	}
	size_t n = (size_t)im->w * im->h * 3;
	im->px = malloc(n);
	if (!im->px || fread(im->px, 1, n, f) != n) {
		fprintf(stderr, "%s: truncated\n", path);
		fclose(f);
		free(im->px);
		return -1;
	}
	fclose(f);
	return 0;
}

static double black_frac(const struct img *im)
{
	size_t n = (size_t)im->w * im->h, dark = 0;
	for (size_t i = 0; i < n; i++) {
		const unsigned char *p = im->px + i * 3;
		if (p[0] * 3 + p[1] * 6 + p[2] < 16 * 10)
			dark++;
	}
	return (double)dark / n;
}

static float *blocks(const struct img *im)
{
	float *b = calloc((size_t)bw * bh * 3, sizeof *b);
	int *cnt = calloc((size_t)bw * bh, sizeof *cnt);
	for (int y = 0; y < im->h; y++)
		for (int x = 0; x < im->w; x++) {
			int i = (y / block) * bw + x / block;
			const unsigned char *p = im->px + ((size_t)y * im->w + x) * 3;
			b[i * 3] += p[0];
			b[i * 3 + 1] += p[1];
			b[i * 3 + 2] += p[2];
			cnt[i]++;
		}
	for (int i = 0; i < bw * bh; i++)
		for (int c = 0; c < 3; c++)
			b[i * 3 + c] /= cnt[i];
	free(cnt);
	return b;
}

static int blk_diff(const float *a, const float *b, int i)
{
	for (int c = 0; c < 3; c++) {
		float d = a[i * 3 + c] - b[i * 3 + c];
		if (d > thr || d < -thr)
			return 1;
	}
	return 0;
}

static int changed(const float *a, const float *b)
{
	int n = 0;
	for (int i = 0; i < bw * bh; i++)
		n += blk_diff(a, b, i);
	return n;
}

static int cmp_str(const void *a, const void *b)
{
	return strcmp(*(char *const *)a, *(char *const *)b);
}

/* argumenty -> serazeny seznam souboru (adresar = vsechny *.ppm v nem) */
static char **list_files(int argc, char **argv, int *count)
{
	char **out = NULL;
	int n = 0, cap = 0;
	for (int i = 0; i < argc; i++) {
		struct stat st;
		if (stat(argv[i], &st) == 0 && S_ISDIR(st.st_mode)) {
			DIR *d = opendir(argv[i]);
			struct dirent *e;
			while (d && (e = readdir(d))) {
				size_t l = strlen(e->d_name);
				if (l < 5 || strcmp(e->d_name + l - 4, ".ppm"))
					continue;
				if (n == cap)
					out = realloc(out, (cap = cap ? cap * 2 : 256) * sizeof *out);
				out[n] = malloc(strlen(argv[i]) + l + 2);
				sprintf(out[n++], "%s/%s", argv[i], e->d_name);
			}
			if (d)
				closedir(d);
		} else {
			if (n == cap)
				out = realloc(out, (cap = cap ? cap * 2 : 256) * sizeof *out);
			out[n++] = strdup(argv[i]);
		}
	}
	qsort(out, n, sizeof *out, cmp_str);
	*count = n;
	return out;
}

static int load_frame(const char *path, struct frame *f, int *w, int *h)
{
	struct img im;
	if (load(path, &im) < 0)
		return -1;
	if (!*w) {
		*w = im.w;
		*h = im.h;
		bw = (im.w + block - 1) / block;
		bh = (im.h + block - 1) / block;
	} else if (im.w != *w || im.h != *h) {
		/* zmena rozliseni = novy rezim, sam o sobe neni chyba; porovnani nema smysl */
		fprintf(stderr, "%s: size %dx%d differs from %dx%d\n", path, im.w, im.h, *w, *h);
		free(im.px);
		return -1;
	}
	const char *slash = strrchr(path, '/');
	f->name = strdup(slash ? slash + 1 : path);
	f->blk = blocks(&im);
	f->black = black_frac(&im);
	free(im.px);
	return 0;
}

static int check(int argc, char **argv)
{
	int nf, w = 0, h = 0, flagged = 0;
	char **files = list_files(argc, argv, &nf);
	if (nf < 1) {
		fprintf(stderr, "no frames\n");
		return 2;
	}
	struct frame *fr = calloc(nf, sizeof *fr);
	int *run = malloc(nf * sizeof *run), *runlen = calloc(nf, sizeof *runlen), nr = 0;
	for (int i = 0; i < nf; i++) {
		if (load_frame(files[i], &fr[i], &w, &h) < 0)
			return 2;
		if (fr[i].black > 0.995 && !allow_black) {
			printf("FLAG black %s dark=%.3f\n", fr[i].name, fr[i].black);
			flagged++;
		}
		if (nr && !changed(fr[run[nr - 1]].blk, fr[i].blk)) {
			runlen[nr - 1]++;
			continue;
		}
		run[nr] = i;
		runlen[nr++] = 1;
	}
	int nb = bw * bh, min_blk = (int)(min_frac * nb + 0.5), same_blk = (int)(same_frac * nb + 0.5);
	if (min_blk < 4)
		min_blk = 4;
	/* spur[r] = bloky, ve kterych se beh r lisi od obou sousedu, a ti se v nich shoduji */
	int *spur = calloc(nr, sizeof *spur);
	for (int r = 1; r + 1 < nr; r++) {
		const float *p = fr[run[r - 1]].blk, *c = fr[run[r]].blk, *n = fr[run[r + 1]].blk;
		for (int i = 0; i < nb; i++)
			spur[r] += blk_diff(c, p, i) && blk_diff(c, n, i) && !blk_diff(p, n, i);
	}
	for (int r = 1; r + 1 < nr; r++) {
		const float *p = fr[run[r - 1]].blk, *c = fr[run[r]].blk, *n = fr[run[r + 1]].blk;
		if (runlen[r] > max_run || fr[run[r]].black > 0.995)
			continue;
		/* soused zavadneho snimku vypada zavadne taky - hlasi se jen silnejsi z nich */
		if (fr[run[r - 1]].black > 0.995 || fr[run[r + 1]].black > 0.995)
			continue;
		int like = -1;
		for (int k = r - 2; k >= 0 && k >= r - back && like < 0; k--)
			if (changed(c, fr[run[k]].blk) <= same_blk)
				like = k;
		int transient = spur[r] >= min_blk && spur[r] >= spur[r - 1] && spur[r] >= spur[r + 1];
		/* navrat ke starsimu stavu, po kterem obraz pokracuje od predchoziho snimku */
		int back_jump = like >= 0 && changed(c, p) >= min_blk && changed(n, p) < changed(n, c);
		if (!transient && !back_jump)
			continue;
		if (like >= 0)
			printf("FLAG regressed %s like=%s blocks=%d/%d frames=%d\n", fr[run[r]].name,
			       fr[run[like]].name, transient ? spur[r] : changed(c, p), nb, runlen[r]);
		else
			printf("FLAG transient %s blocks=%d/%d frames=%d\n", fr[run[r]].name, spur[r], nb, runlen[r]);
		flagged++;
	}
	free(spur);
	printf("frames=%d runs=%d size=%dx%d grid=%dx%d flagged=%d\n", nf, nr, w, h, bw, bh, flagged);
	return flagged ? 1 : 0;
}

static int stat_files(int argc, char **argv)
{
	int rc = 0;
	for (int i = 0; i < argc; i++) {
		struct img im;
		if (load(argv[i], &im) < 0) {
			rc = 1;
			continue;
		}
		/* pocet ruznych barev (5 bitu na kanal staci pro "neni prazdny") */
		static unsigned char seen[1 << 15];
		memset(seen, 0, sizeof seen);
		int colors = 0;
		size_t n = (size_t)im.w * im.h;
		for (size_t j = 0; j < n; j++) {
			const unsigned char *p = im.px + j * 3;
			int k = (p[0] >> 3) << 10 | (p[1] >> 3) << 5 | p[2] >> 3;
			colors += !seen[k];
			seen[k] = 1;
		}
		printf("%s %dx%d colors=%d nonblack=%.3f\n", argv[i], im.w, im.h, colors, 1 - black_frac(&im));
		free(im.px);
	}
	return rc;
}

int main(int argc, char **argv)
{
	if (argc >= 3 && !strcmp(argv[1], "stat"))
		return stat_files(argc - 2, argv + 2);
	if (argc == 4 && !strcmp(argv[1], "diff")) {
		struct frame a, b;
		int w = 0, h = 0;
		if (load_frame(argv[2], &a, &w, &h) < 0 || load_frame(argv[3], &b, &w, &h) < 0)
			return 2;
		printf("%.4f\n", (double)changed(a.blk, b.blk) / (bw * bh));
		return 0;
	}
	if (argc >= 3 && !strcmp(argv[1], "check")) {
		int i = 2;
		for (; i < argc && !strncmp(argv[i], "--", 2); i++) {
			if (!strcmp(argv[i], "--allow-black"))
				allow_black = 1;
			else if (i + 1 < argc && !strcmp(argv[i], "--block"))
				block = atoi(argv[++i]);
			else if (i + 1 < argc && !strcmp(argv[i], "--thr"))
				thr = atof(argv[++i]);
			else if (i + 1 < argc && !strcmp(argv[i], "--min"))
				min_frac = atof(argv[++i]);
			else if (i + 1 < argc && !strcmp(argv[i], "--same"))
				same_frac = atof(argv[++i]);
			else if (i + 1 < argc && !strcmp(argv[i], "--max-run"))
				max_run = atoi(argv[++i]);
			else if (i + 1 < argc && !strcmp(argv[i], "--back"))
				back = atoi(argv[++i]);
			else {
				fprintf(stderr, "unknown option %s\n", argv[i]);
				return 2;
			}
		}
		if (block < 1)
			block = 1;
		return check(argc - i, argv + i);
	}
	fprintf(stderr, "usage: wlt-frames stat FILE.. | diff A B | check [opts] DIR|FILE..\n");
	return 2;
}
