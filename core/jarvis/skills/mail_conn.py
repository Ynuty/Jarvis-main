"""
============================================================
 Подключения к почте. Пароли и токены — только в хранилище
 учётных данных ОС (keyring → Windows Credential Manager / DPAPI).
   ImapConn  — Яндекс, Mail.ru, Gmail (пароль приложения), любой IMAP.
   GmailConn — Gmail API по OAuth (scope gmail.modify — минимальный,
               который позволяет перекладывать и помечать письма).
 Содержимое писем никуда, кроме самого почтового сервера, не уходит.
============================================================
"""
from __future__ import annotations

import base64
import email
import email.header
import email.utils
import hashlib
import imaplib
import json
import re
import secrets
import socket
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import keyring

SERVICE = "jarvis-mail"

IMAP_HOSTS = {
    "yandex.ru": "imap.yandex.ru", "ya.ru": "imap.yandex.ru", "yandex.com": "imap.yandex.com",
    "mail.ru": "imap.mail.ru", "inbox.ru": "imap.mail.ru", "list.ru": "imap.mail.ru", "bk.ru": "imap.mail.ru",
    "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com", "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com", "rambler.ru": "imap.rambler.ru",
}


@dataclass
class Msg:
    uid: str
    message_id: str
    from_name: str
    from_addr: str
    subject: str
    date: float
    snippet: str = ""
    unsubscribe: str = ""
    folder: str = "INBOX"
    headers: dict = field(default_factory=dict)

    def short(self) -> dict:
        return {"uid": self.uid, "from": self.from_name or self.from_addr, "addr": self.from_addr,
                "subject": self.subject, "date": self.date, "snippet": self.snippet[:200]}


# ---------- секреты ----------

def secret_key(profile_id: int, address: str) -> str:
    return f"{profile_id}:{address.lower()}"


def save_secret(profile_id: int, address: str, value: str) -> str:
    ref = secret_key(profile_id, address)
    keyring.set_password(SERVICE, ref, value)
    return ref


def load_secret(ref: str) -> str | None:
    return keyring.get_password(SERVICE, ref)


def drop_secret(ref: str) -> None:
    try:
        keyring.delete_password(SERVICE, ref)
    except keyring.errors.PasswordDeleteError:
        pass


# ---------- modified UTF-7 для имён папок IMAP (RFC 3501) ----------

def imap_utf7_encode(s: str) -> str:
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append("&" + b + "-")
            buf.clear()

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def imap_utf7_decode(s: str) -> str:
    def dec(m):
        body = m.group(1)
        if not body:
            return "&"
        b = body.replace(",", "/")
        b += "=" * (-len(b) % 4)
        return base64.b64decode(b).decode("utf-16-be")
    return re.sub(r"&([^-]*)-", dec, s)


def _hdr(v: str | None) -> str:
    if not v:
        return ""
    parts = []
    for text, enc in email.header.decode_header(v):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(enc or "utf-8", "replace"))
            except LookupError:
                parts.append(text.decode("utf-8", "replace"))
        else:
            parts.append(text)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def body_text(msg: Message, limit: int = 20000) -> str:
    """Текст письма: text/plain, иначе text/html без тегов."""
    plain, html_ = "", ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if part.get("Content-Disposition", "").startswith("attachment"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if ctype == "text/plain" and not plain:
            plain = text
        elif ctype == "text/html" and not html_:
            html_ = text
    if not plain and html_:
        import html as h
        plain = h.unescape(re.sub(r"<(script|style).*?</\1>|<[^>]+>", " ", html_, flags=re.S | re.I))
    return re.sub(r"\s+", " ", plain).strip()[:limit]


def _parse(uid: str, raw: bytes, folder: str) -> Msg:
    m = email.message_from_bytes(raw)
    name, addr = email.utils.parseaddr(_hdr(m.get("From")))
    try:
        date = email.utils.parsedate_to_datetime(m.get("Date")).timestamp()
    except (TypeError, ValueError):
        date = time.time()
    unsub = m.get("List-Unsubscribe", "") or ""
    https = re.search(r"<(https?://[^>]+)>", unsub)
    return Msg(uid=uid, message_id=(m.get("Message-ID") or "").strip(), from_name=name, from_addr=addr.lower(),
               subject=_hdr(m.get("Subject")), date=date, snippet=body_text(m, 400) if m.get_payload() else "",
               unsubscribe=https.group(1) if https else "", folder=folder,
               headers={"list_id": m.get("List-Id", ""), "precedence": m.get("Precedence", "")})


class ImapConn:
    kind = "imap"

    def __init__(self, address: str, password: str, host: str = "") -> None:
        self.address = address
        self.password = password
        self.host = host or IMAP_HOSTS.get(address.split("@")[-1].lower(), "imap." + address.split("@")[-1])
        self.lock = threading.Lock()
        self.c: imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        socket.setdefaulttimeout(20)
        self.c = imaplib.IMAP4_SSL(self.host, 993)
        self.c.login(self.address, self.password)

    def _c(self) -> imaplib.IMAP4_SSL:
        if self.c is None:
            self.connect()
        try:
            self.c.noop()
        except (imaplib.IMAP4.abort, OSError):
            self.connect()
        return self.c

    def close(self) -> None:
        if self.c:
            try:
                self.c.logout()
            except Exception:  # noqa: BLE001
                pass
            self.c = None

    def folders(self) -> list[str]:
        typ, data = self._c().list()
        out = []
        for line in data or []:
            s = line.decode() if isinstance(line, bytes) else str(line)
            m = re.search(r'"([^"]*)"\s*$|\s(\S+)$', s)
            if m:
                out.append(imap_utf7_decode(m.group(1) or m.group(2)))
        return out

    def special(self, flag: str) -> str | None:
        """\\Junk, \\Trash, \\Archive — у каждого провайдера свои имена."""
        typ, data = self._c().list()
        for line in data or []:
            s = line.decode() if isinstance(line, bytes) else str(line)
            if flag.lower() in s.lower():
                m = re.search(r'"([^"]*)"\s*$|\s(\S+)$', s)
                if m:
                    return imap_utf7_decode(m.group(1) or m.group(2))
        return None

    def ensure_folder(self, name: str) -> None:
        if name not in self.folders():
            self._c().create(f'"{imap_utf7_encode(name)}"')

    def list_messages(self, folder: str = "INBOX", unseen: bool = True, limit: int = 200) -> list[Msg]:
        with self.lock:
            c = self._c()
            c.select(f'"{imap_utf7_encode(folder)}"', readonly=True)
            typ, data = c.uid("search", None, "UNSEEN" if unseen else "ALL")
            uids = (data[0] or b"").split()[-limit:]
            out = []
            for i in range(0, len(uids), 50):
                batch = b",".join(uids[i:i + 50])
                typ, rows = c.uid("fetch", batch, "(UID BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.1500>)")
                cur_uid, hdr, txt = None, b"", b""
                for row in rows or []:
                    if not isinstance(row, tuple):
                        if cur_uid and hdr:
                            out.append(_parse(cur_uid, hdr + b"\r\n" + txt, folder))
                        cur_uid, hdr, txt = None, b"", b""
                        continue
                    meta = row[0].decode(errors="replace")
                    if um := re.search(r"UID (\d+)", meta):
                        cur_uid = um.group(1)
                    if "HEADER" in meta:
                        hdr = row[1]
                    elif "TEXT" in meta:
                        txt = row[1]
                if cur_uid and hdr:
                    out.append(_parse(cur_uid, hdr + b"\r\n" + txt, folder))
            return out

    def fetch_body(self, uid: str, folder: str = "INBOX") -> str:
        with self.lock:
            c = self._c()
            c.select(f'"{imap_utf7_encode(folder)}"', readonly=True)
            typ, rows = c.uid("fetch", uid, "(BODY.PEEK[])")
            raw = next((r[1] for r in rows or [] if isinstance(r, tuple)), b"")
            return body_text(email.message_from_bytes(raw))

    def move(self, uids: list[str], dest: str, src: str = "INBOX") -> None:
        if not uids:
            return
        with self.lock:
            c = self._c()
            self.ensure_folder(dest)
            c.select(f'"{imap_utf7_encode(src)}"')
            seq = ",".join(uids)
            enc = f'"{imap_utf7_encode(dest)}"'
            typ, _ = c.uid("MOVE", seq, enc) if b"MOVE" in b" ".join(c.capabilities) else ("NO", None)
            if typ != "OK":
                c.uid("COPY", seq, enc)
                c.uid("STORE", seq, "+FLAGS", r"(\Deleted)")
                c.expunge()

    def mark_read(self, uids: list[str], folder: str = "INBOX") -> None:
        if not uids:
            return
        with self.lock:
            c = self._c()
            c.select(f'"{imap_utf7_encode(folder)}"')
            c.uid("STORE", ",".join(uids), "+FLAGS", r"(\Seen)")

    def find_by_message_id(self, folder: str, message_id: str) -> str | None:
        with self.lock:
            c = self._c()
            c.select(f'"{imap_utf7_encode(folder)}"', readonly=True)
            typ, data = c.uid("search", None, "HEADER", "Message-ID", message_id)
            uids = (data[0] or b"").split()
            return uids[-1].decode() if uids else None

    def trash_folder(self) -> str:
        return self.special("\\Trash") or "Trash"

    def junk_folder(self) -> str:
        return self.special("\\Junk") or "Spam"


# ---------- Gmail API ----------

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GAPI = "https://gmail.googleapis.com/gmail/v1/users/me"


def gmail_oauth(client_id: str, client_secret: str, open_browser) -> dict:
    """
    OAuth для установленного приложения: PKCE + приём кода на 127.0.0.1.
    client_id / secret пользователь создаёт сам в Google Cloud Console (тип «Desktop app»).
    """
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    box: dict = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                box["code"] = q.get("code", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Готово. Вернитесь в Джарвис — окно можно закрыть.".encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": GMAIL_SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "access_type": "offline", "prompt": "consent"})
    open_browser(url)
    srv.timeout = 180
    deadline = time.time() + 180
    while "code" not in box and time.time() < deadline:
        srv.handle_request()
    srv.server_close()
    if not box.get("code"):
        raise RuntimeError("не дождался входа в Google")
    r = httpx.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id, "client_secret": client_secret, "code": box["code"], "code_verifier": verifier,
        "grant_type": "authorization_code", "redirect_uri": redirect}, timeout=20)
    r.raise_for_status()
    tok = r.json()
    return {"client_id": client_id, "client_secret": client_secret, "refresh_token": tok["refresh_token"]}


class GmailConn:
    kind = "gmail"

    def __init__(self, address: str, cred: dict) -> None:
        self.address = address
        self.cred = cred
        self.access = ""
        self.exp = 0.0
        self._labels: dict[str, str] = {}

    def _token(self) -> str:
        if time.time() > self.exp - 60:
            r = httpx.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.cred["client_id"], "client_secret": self.cred["client_secret"],
                "refresh_token": self.cred["refresh_token"], "grant_type": "refresh_token"}, timeout=20)
            r.raise_for_status()
            d = r.json()
            self.access, self.exp = d["access_token"], time.time() + d.get("expires_in", 3600)
        return self.access

    def _req(self, method: str, path: str, **kw) -> dict:
        r = httpx.request(method, GAPI + path, headers={"Authorization": "Bearer " + self._token()}, timeout=30, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    def close(self) -> None:
        pass

    def labels(self) -> dict[str, str]:
        if not self._labels:
            self._labels = {lb["name"]: lb["id"] for lb in self._req("GET", "/labels").get("labels", [])}
        return self._labels

    def ensure_folder(self, name: str) -> str:
        labs = self.labels()
        if name not in labs:
            lb = self._req("POST", "/labels", json={"name": name})
            labs[name] = lb["id"]
        return labs[name]

    def list_messages(self, folder: str = "INBOX", unseen: bool = True, limit: int = 200) -> list[Msg]:
        q = "in:inbox" if folder == "INBOX" else f'label:"{folder}"'
        if unseen:
            q += " is:unread"
        ids = self._req("GET", "/messages", params={"q": q, "maxResults": min(limit, 500)}).get("messages", [])
        out = []
        for it in ids:
            m = self._req("GET", f"/messages/{it['id']}", params=[("format", "metadata"),
                          ("metadataHeaders", "From"), ("metadataHeaders", "Subject"), ("metadataHeaders", "Date"),
                          ("metadataHeaders", "List-Unsubscribe"), ("metadataHeaders", "List-Id")])
            h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
            name, addr = email.utils.parseaddr(h.get("from", ""))
            https = re.search(r"<(https?://[^>]+)>", h.get("list-unsubscribe", ""))
            out.append(Msg(uid=m["id"], message_id=m["id"], from_name=name, from_addr=addr.lower(),
                           subject=h.get("subject", ""), date=int(m.get("internalDate", "0")) / 1000,
                           snippet=m.get("snippet", ""), unsubscribe=https.group(1) if https else "",
                           folder=folder, headers={"list_id": h.get("list-id", "")}))
        return out

    def fetch_body(self, uid: str, folder: str = "INBOX") -> str:
        m = self._req("GET", f"/messages/{uid}", params={"format": "raw"})
        raw = base64.urlsafe_b64decode(m["raw"] + "==")
        return body_text(email.message_from_bytes(raw))

    def move(self, uids: list[str], dest: str, src: str = "INBOX") -> None:
        if not uids:
            return
        add = [self.ensure_folder(dest)] if dest not in ("INBOX", "SPAM", "TRASH") else [dest]
        remove = ["INBOX"] if src == "INBOX" else [self.labels().get(src, src)]
        self._req("POST", "/messages/batchModify", json={"ids": uids, "addLabelIds": add, "removeLabelIds": remove})

    def mark_read(self, uids: list[str], folder: str = "INBOX") -> None:
        if uids:
            self._req("POST", "/messages/batchModify", json={"ids": uids, "removeLabelIds": ["UNREAD"]})

    def find_by_message_id(self, folder: str, message_id: str) -> str | None:
        return message_id                       # у Gmail id стабилен

    def trash_folder(self) -> str:
        return "TRASH"

    def junk_folder(self) -> str:
        return "SPAM"


def connect(kind: str, address: str, host: str, secret: str):
    if kind == "gmail":
        return GmailConn(address, json.loads(secret))
    return ImapConn(address, secret, host)
