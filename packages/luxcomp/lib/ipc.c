/*
 * IPC soket pro shell (luxwm-ipc.md). Jadro dela jen prenos: soket UNIX, kontrolu SO_PEERCRED
 * (stejny uid), privilegium podle allowlistu, radky dovnitr a frontu ven. Co radky znamenaji,
 * rozhoduje politika (luxwm v LSL). LSL getsockopt nema, proto je tohle v C.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include "internal.h"

#define MAX_CLIENTS 32
#define MAX_LINE (64 * 1024)
#define MAX_PENDING (1024 * 1024)

struct ipc_client {
	struct wl_list link;
	int64_t id;
	int fd;
	struct wl_event_source *source;
	char *in;
	size_t in_len;
	char *out;
	size_t out_len;
	char *line;		/* the line being delivered, valid until the next dispatch */
};

static struct {
	int fd;
	char *path;
	struct wl_event_source *source;
	struct wl_list clients;
	int count;
} ipc = { .fd = -1 };

static struct ipc_client *
client_by_id(int64_t id)
{
	struct ipc_client *c;
	if (ipc.fd < 0) {
		return NULL;
	}
	wl_list_for_each(c, &ipc.clients, link) {
		if (c->id == id) {
			return c;
		}
	}
	return NULL;
}

static void
client_free(struct ipc_client *c, bool notify)
{
	int64_t id = c->id;
	wl_list_remove(&c->link);
	wl_event_source_remove(c->source);
	close(c->fd);
	free(c->in);
	free(c->out);
	free(c->line);
	free(c);
	ipc.count--;
	if (notify) {
		emit(LUXCOMP_EV_IPC_CLOSE, id, 0, 0, 0);
	}
}

static void
client_watch(struct ipc_client *c)
{
	wl_event_source_fd_update(c->source,
		WL_EVENT_READABLE | (c->out_len ? WL_EVENT_WRITABLE : 0));
}

static bool
client_flush(struct ipc_client *c)
{
	while (c->out_len) {
		ssize_t n = send(c->fd, c->out, c->out_len, MSG_NOSIGNAL | MSG_DONTWAIT);
		if (n < 0) {
			if (errno == EAGAIN || errno == EWOULDBLOCK) {
				break;
			}
			if (errno == EINTR) {
				continue;
			}
			return false;
		}
		memmove(c->out, c->out + n, c->out_len - n);
		c->out_len -= n;
	}
	client_watch(c);
	return true;
}

/* Kazdy uplny radek jde politice jako jedna udalost. Klient muze behem udalosti zmizet
 * (politika ho zavre), proto se po kazde udalosti hleda znovu podle id. */
static bool
client_read(struct ipc_client *c)
{
	int64_t id = c->id;
	char buf[4096];
	ssize_t n = recv(c->fd, buf, sizeof(buf), MSG_DONTWAIT);
	if (n == 0) {
		return false;
	}
	if (n < 0) {
		return errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR;
	}
	if (c->in_len + n > MAX_LINE) {
		fprintf(stderr, "luxcomp: ipc: line too long, client %lld dropped\n", (long long)id);
		return false;
	}
	char *in = realloc(c->in, c->in_len + n);
	if (!in) {
		return false;
	}
	c->in = in;
	memcpy(c->in + c->in_len, buf, n);
	c->in_len += n;
	for (;;) {
		char *nl = memchr(c->in, '\n', c->in_len);
		if (!nl) {
			break;
		}
		size_t len = nl - c->in;
		free(c->line);
		c->line = strndup(c->in, len);
		memmove(c->in, nl + 1, c->in_len - len - 1);
		c->in_len -= len + 1;
		if (c->line && *c->line) {
			emit(LUXCOMP_EV_IPC_LINE, id, 0, 0, 0);
			c = client_by_id(id);
			if (!c) {
				return true;
			}
		}
	}
	return true;
}

static int
client_event(int fd, uint32_t mask, void *data)
{
	struct ipc_client *c = data;
	bool alive = !(mask & (WL_EVENT_HANGUP | WL_EVENT_ERROR)) || (mask & WL_EVENT_READABLE);
	int64_t id = c->id;
	if (alive && (mask & WL_EVENT_WRITABLE)) {
		alive = client_flush(c);
	}
	if (alive && (mask & WL_EVENT_READABLE)) {
		alive = client_read(c);
		c = client_by_id(id);
		if (!c) {
			return 0;
		}
	}
	if (!alive) {
		client_free(c, true);
	}
	return 0;
}

static int
server_event(int fd, uint32_t mask, void *data)
{
	int cfd = accept4(ipc.fd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
	if (cfd < 0) {
		return 0;
	}
	struct ucred cred;
	socklen_t len = sizeof(cred);
	if (getsockopt(cfd, SOL_SOCKET, SO_PEERCRED, &cred, &len) < 0 || cred.uid != geteuid()) {
		fprintf(stderr, "luxcomp: ipc: rejected uid %d pid %d\n",
			len == sizeof(cred) ? (int)cred.uid : -1, len == sizeof(cred) ? (int)cred.pid : -1);
		close(cfd);
		return 0;
	}
	if (ipc.count >= MAX_CLIENTS) {
		fprintf(stderr, "luxcomp: ipc: too many clients, pid %d rejected\n", (int)cred.pid);
		close(cfd);
		return 0;
	}
	struct ipc_client *c = calloc(1, sizeof(*c));
	if (!c) {
		close(cfd);
		return 0;
	}
	c->id = ++comp.next_id;
	c->fd = cfd;
	c->source = wl_event_loop_add_fd(comp.loop, cfd, WL_EVENT_READABLE, client_event, c);
	wl_list_insert(ipc.clients.prev, &c->link);
	ipc.count++;
	emit(LUXCOMP_EV_IPC_CONNECT, c->id, cred.pid, pid_privileged(cred.pid), 0);
	return 0;
}

/* Zivy soket jineho kompozitoru se neprepise, mrtvy po padu se smaze */
static bool
path_in_use(const struct sockaddr_un *addr)
{
	int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
	if (fd < 0) {
		return false;
	}
	bool used = connect(fd, (const struct sockaddr *)addr, sizeof(*addr)) == 0;
	close(fd);
	return used;
}

int64_t
luxcomp_ipc_listen(const char *path)
{
	struct sockaddr_un addr = { .sun_family = AF_UNIX };
	if (!path || !*path || ipc.fd >= 0 || strlen(path) >= sizeof(addr.sun_path)) {
		return -1;
	}
	strcpy(addr.sun_path, path);
	if (path_in_use(&addr)) {
		fprintf(stderr, "luxcomp: ipc: %s is in use\n", path);
		return -1;
	}
	unlink(path);
	int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
	if (fd < 0) {
		return -1;
	}
	/* prava hned pri vytvoreni, ne az po bind (jinak kratka chvile s umask) */
	mode_t old = umask(0177);
	int ok = bind(fd, (struct sockaddr *)&addr, sizeof(addr));
	umask(old);
	if (ok < 0 || listen(fd, 16) < 0) {
		close(fd);
		return -1;
	}
	ipc.fd = fd;
	ipc.path = strdup(path);
	wl_list_init(&ipc.clients);
	ipc.source = wl_event_loop_add_fd(comp.loop, fd, WL_EVENT_READABLE, server_event, NULL);
	return 0;
}

const char *
luxcomp_ipc_line(int64_t client)
{
	struct ipc_client *c = client_by_id(client);
	return c && c->line ? c->line : "";
}

int64_t
luxcomp_ipc_send(int64_t client, const char *line)
{
	struct ipc_client *c = client_by_id(client);
	if (!c || !line) {
		return 0;
	}
	size_t len = strlen(line);
	if (c->out_len + len + 1 > MAX_PENDING) {
		fprintf(stderr, "luxcomp: ipc: client %lld does not read, dropped\n", (long long)client);
		client_free(c, false);
		return 0;
	}
	char *out = realloc(c->out, c->out_len + len + 1);
	if (!out) {
		return 0;
	}
	c->out = out;
	memcpy(c->out + c->out_len, line, len);
	c->out[c->out_len + len] = '\n';
	c->out_len += len + 1;
	/* bez udalosti IPC_CLOSE: volajici je prave v obsluze udalosti, 0 mu staci */
	if (!client_flush(c)) {
		client_free(c, false);
		return 0;
	}
	return 1;
}

void
luxcomp_ipc_close(int64_t client)
{
	struct ipc_client *c = client_by_id(client);
	if (c) {
		client_flush(c);
		client_free(c, false);
	}
}

void
ipc_finish(void)
{
	if (ipc.fd < 0) {
		return;
	}
	struct ipc_client *c, *tmp;
	wl_list_for_each_safe(c, tmp, &ipc.clients, link) {
		client_free(c, false);
	}
	wl_event_source_remove(ipc.source);
	close(ipc.fd);
	unlink(ipc.path);
	free(ipc.path);
	ipc.fd = -1;
}
