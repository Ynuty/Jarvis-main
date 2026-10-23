"""
============================================================
 API ядра: FastAPI на 127.0.0.1.
   REST  — профили, вход, настройки, память, журнал, день, корзина,
           почта, документы, мастер первого запуска, экспорт/импорт.
   WS    — /ws: события в реальном времени, аудио микрофона (PCM16
           16 кГц моно, бинарные кадры) и озвучка (WAV, бинарные кадры).
 Защита: слушаем только loopback; общий секрет оболочки в заголовке
 X-Jarvis-Secret (или ?s= для WS) — чужие страницы в браузере не
 дотянутся до API; проверка Host против DNS-rebinding.
============================================================
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from .. import __version__, auth, config, journal
from ..db import get_db, loads
from ..engines import engines, hw_detect
from ..session import Session
from ..skills import TOOLS, day as day_skill, knowledge, mail as mail_skill, memory as memory_skill
from ..skills import order as order_skill

log = logging.getLogger("jarvis.api")
app = FastAPI(title="J.A.R.V.I.S. core", version=__version__, docs_url=None, redoc_url=None)
sessions: dict[int, Session] = {}
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


# ---------- защита ----------

@app.middleware("http")
async def guard(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":")[0]
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "bad host"}, status_code=403)
    if config.LAUNCH_SECRET and request.url.path.startswith("/api") and request.method != "OPTIONS":
        if request.headers.get("x-jarvis-secret") != config.LAUNCH_SECRET:
            return JSONResponse({"detail": "forbidden"}, status_code=403)
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# Окно Electron грузится с file:// (Origin: null), в разработке — с Vite.
# CORS сам по себе не защита: доступ закрывает секрет оболочки выше.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(CORSMiddleware, allow_origins=["null", "http://127.0.0.1:5173", "http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"])


def me(authorization: str = Header("")) -> auth.Token:
    try:
        return auth.check(authorization.removeprefix("Bearer ").strip())
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from None


def session_for(t: auth.Token) -> Session:
    s = sessions.get(t.profile_id)
    if s is None:
        s = Session(get_db(), t.profile_id, t.name)
        sessions[t.profile_id] = s
    return s


def err(e: Exception, code: int = 400):
    raise HTTPException(code, str(e)) from None


# ---------- служебное ----------

@app.get("/api/health")
async def health():
    return {"ok": True, "version": __version__, "engines": engines.status, "llm": engines.llm_ok,
            "home": str(config.HOME)}


@app.on_event("startup")
async def startup():
    get_db()
    asyncio.create_task(engines.check_llm(config.DEFAULT_SETTINGS["llm_model"]))
    # голос и слух — сразу при старте с настройками последнего профиля, не дожидаясь входа
    db = get_db()
    last = db.one("SELECT profile_id FROM settings WHERE key='wizard_done' ORDER BY rowid DESC LIMIT 1")
    from ..settings import Settings
    engines.load_voice(Settings(db, last["profile_id"]).all() if last else dict(config.DEFAULT_SETTINGS))
    from ..skills import desktop
    asyncio.create_task(asyncio.to_thread(desktop.app_index))     # индекс программ — заранее, в фоне


# ---------- профили и вход ----------

class NewProfile(BaseModel):
    name: str
    secret: str
    kind: str = "pin"
    avatar: str = ""


class Login(BaseModel):
    profile_id: int
    secret: str


@app.get("/api/profiles")
def profiles():
    return auth.list_profiles(get_db())


@app.post("/api/profiles")
def create_profile(p: NewProfile):
    try:
        pid = auth.create_profile(get_db(), p.name, p.secret, p.kind, p.avatar)
    except auth.AuthError as e:
        err(e)
    return {"id": pid}


@app.post("/api/login")
def login(p: Login):
    db = get_db()
    try:
        tok = auth.login(db, p.profile_id, p.secret)
    except auth.AuthError as e:
        err(e, 401)
    t = auth.check(tok)
    s = session_for(t)
    engines.load_voice(s.settings.all())
    first = not s.settings.get("wizard_done", False)
    return {"token": tok, "profile": {"id": t.profile_id, "name": t.name}, "first_run": first}


class PhraseLogin(BaseModel):
    profile_id: int
    phrase: str


@app.post("/api/login/phrase")
def login_phrase(p: PhraseLogin):
    try:
        tok = auth.login_by_phrase(get_db(), p.profile_id, p.phrase)
    except auth.AuthError as e:
        err(e, 401)
    t = auth.check(tok)
    engines.load_voice(session_for(t).settings.all())
    return {"token": tok, "profile": {"id": t.profile_id, "name": t.name}, "first_run": False}


@app.post("/api/logout")
def logout(authorization: str = Header("")):
    auth.logout(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


class SecretChange(BaseModel):
    old: str
    new: str
    kind: str = "pin"


@app.post("/api/me/secret")
def change_secret(p: SecretChange, t: auth.Token = Depends(me)):
    try:
        auth.change_secret(get_db(), t.profile_id, p.old, p.new, p.kind)
    except auth.AuthError as e:
        err(e)
    return {"ok": True}


class VoicePhrase(BaseModel):
    phrase: str = ""


@app.post("/api/me/voice-phrase")
def voice_phrase(p: VoicePhrase, t: auth.Token = Depends(me)):
    auth.set_voice_phrase(get_db(), t.profile_id, p.phrase or None)
    return {"ok": True}


class Confirm(BaseModel):
    secret: str


@app.post("/api/me/wipe")
async def wipe(p: Confirm, t: auth.Token = Depends(me)):
    db = get_db()
    if not auth.verify(db, t.profile_id, p.secret):
        raise HTTPException(401, "Неверный PIN или пароль")
    s = sessions.pop(t.profile_id, None)
    if s:
        s.clear_timers()
    auth.wipe_profile(db, t.profile_id)
    return {"ok": True}


class ExportReq(BaseModel):
    password: str


@app.post("/api/me/export")
def export(p: ExportReq, t: auth.Token = Depends(me)):
    try:
        blob = auth.export_profile(get_db(), t.profile_id, p.password)
    except auth.AuthError as e:
        err(e)
    name = f"jarvis-{t.name}-{time.strftime('%Y%m%d')}.jarvis"
    return Response(blob, media_type="application/octet-stream",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{httpx.URL(name).raw_path.decode()}"})


@app.post("/api/import")
async def import_profile(file: UploadFile = File(...), password: str = Form(...)):
    try:
        pid = auth.import_profile(get_db(), await file.read(), password)
    except auth.AuthError as e:
        err(e)
    return {"id": pid}


# ---------- настройки ----------

SAFE_KEYS = set(config.DEFAULT_SETTINGS) | {"system_prompt", "wizard_done", "disabled_tools", "order_automation",
                                            "avatar"}


@app.get("/api/settings")
def get_settings(t: auth.Token = Depends(me)):
    s = session_for(t)
    return {"settings": s.settings.all(), "profiles": config.PROFILES, "tools": [
        {"name": x.name, "skill": x.skill, "title": x.title, "risk": x.risk.value, "network": x.network}
        for x in TOOLS.values()]}


@app.put("/api/settings")
async def put_settings(values: dict[str, Any], t: auth.Token = Depends(me)):
    s = session_for(t)
    bad = [k for k in values if k not in SAFE_KEYS]
    if bad:
        raise HTTPException(400, "неизвестные ключи: " + ", ".join(bad))
    s.settings.update(values)
    if "listen_mode" in values:
        s.mode = values["listen_mode"]
    if values.keys() & {"whisper_model", "whisper_device", "tts_engine", "tts_voice", "tts_rate"}:
        engines.load_voice(s.settings.all())
    if "llm_model" in values:
        await engines.check_llm(values["llm_model"])
    if "avatar" in values:
        get_db().run("UPDATE profiles SET avatar=? WHERE id=?", (values["avatar"], t.profile_id))
    await s.emit({"type": "settings", "settings": s.settings.all()})
    return {"ok": True}


@app.get("/api/tts/sample")
async def tts_sample(t: auth.Token = Depends(me)):
    s = session_for(t)
    tts = engines.tts
    if not tts or not tts.ready:
        raise HTTPException(409, engines.status["tts"])
    text = f"Добрый день, {s.settings.get('address_as', 'сэр')}. Все системы в норме. Я к вашим услугам."
    return Response(await asyncio.to_thread(tts.synth, text), media_type="audio/wav")


@app.get("/api/prompt/default")
def default_prompt(t: auth.Token = Depends(me)):
    return {"prompt": (config.PROMPTS_DIR / "system_ru.md").read_text(encoding="utf-8")}


# ---------- память ----------

class Fact(BaseModel):
    fact: str
    category: str = "общее"


@app.get("/api/memory")
def memory_list(t: auth.Token = Depends(me)):
    return memory_skill.facts(get_db(), t.profile_id)


@app.post("/api/memory")
def memory_add(f: Fact, t: auth.Token = Depends(me)):
    return {"id": memory_skill.upsert(get_db(), t.profile_id, f.fact, f.category)}


@app.put("/api/memory/{fid}")
def memory_edit(fid: int, f: Fact, t: auth.Token = Depends(me)):
    get_db().run("UPDATE memory SET fact=?, category=?, updated_at=? WHERE id=? AND profile_id=?",
                 (f.fact, f.category, time.time(), fid, t.profile_id))
    return {"ok": True}


@app.delete("/api/memory/{fid}")
def memory_del(fid: int, t: auth.Token = Depends(me)):
    get_db().run("DELETE FROM memory WHERE id=? AND profile_id=?", (fid, t.profile_id))
    return {"ok": True}


@app.delete("/api/history")
def history_clear(t: auth.Token = Depends(me)):
    db = get_db()
    db.run("DELETE FROM messages WHERE profile_id=?", (t.profile_id,))
    db.run("DELETE FROM summaries WHERE profile_id=?", (t.profile_id,))
    return {"ok": True}


# ---------- журнал и день ----------

@app.get("/api/journal")
def journal_list(limit: int = 200, skill: str | None = None, t: auth.Token = Depends(me)):
    return journal.recent(get_db(), t.profile_id, min(limit, 1000), skill=skill)


@app.get("/api/day")
def day(ts: float | None = None, t: auth.Token = Depends(me)):
    db = get_db()
    a, b = day_skill.day_bounds(ts)
    done = [e for e in journal.recent(db, t.profile_id, 300, since=a) if e["status"] == "done" and e["ts"] < b]
    return {"start": a, "tasks": day_skill.tasks_for_day(db, t.profile_id, ts), "done": done}


class TaskIn(BaseModel):
    title: str
    when: str = ""
    due_at: float | None = None


@app.post("/api/tasks")
async def task_add(p: TaskIn, t: auth.Token = Depends(me)):
    s = session_for(t)
    from ..skills.base import Ctx
    args = p.model_dump()
    if p.due_at is None and not p.when:            # «созвон в 15:00» → название + время
        args["title"], args["due_at"] = day_skill.parse_when(p.title)
        args["title"] = args["title"] or p.title
    r = await s.call_tool(Ctx(s, user_text="добавь задачу"), "task.add", args, origin="rule")
    return {"ok": r.ok, "say": r.say}


class TaskPatch(BaseModel):
    title: str | None = None
    status: str | None = None
    due_at: float | None = None


@app.put("/api/tasks/{tid}")
async def task_edit(tid: int, p: TaskPatch, t: auth.Token = Depends(me)):
    db = get_db()
    if p.title is not None:
        db.run("UPDATE tasks SET title=? WHERE id=? AND profile_id=?", (p.title, tid, t.profile_id))
    if p.status is not None:
        db.run("UPDATE tasks SET status=?, done_at=? WHERE id=? AND profile_id=?",
               (p.status, time.time() if p.status == "done" else None, tid, t.profile_id))
        row = db.one("SELECT title FROM tasks WHERE id=?", (tid,))
        if p.status == "done" and row:
            journal.log(db, t.profile_id, skill="day", tool="task.done", risk="local", status="done",
                        summary=f"Отмечено: {row['title']}", source="user")
    if "due_at" in p.model_fields_set:
        db.run("UPDATE tasks SET due_at=? WHERE id=? AND profile_id=?", (p.due_at, tid, t.profile_id))
    await session_for(t).emit({"type": "day"})
    return {"ok": True}


@app.delete("/api/tasks/{tid}")
async def task_del(tid: int, t: auth.Token = Depends(me)):
    get_db().run("UPDATE tasks SET status='cancelled' WHERE id=? AND profile_id=?", (tid, t.profile_id))
    await session_for(t).emit({"type": "day"})
    return {"ok": True}


@app.get("/api/notes")
def notes(t: auth.Token = Depends(me)):
    return [dict(r) for r in get_db().q("SELECT * FROM notes WHERE profile_id=? ORDER BY id DESC", (t.profile_id,))]


@app.delete("/api/notes/{nid}")
def note_del(nid: int, t: auth.Token = Depends(me)):
    get_db().run("DELETE FROM notes WHERE id=? AND profile_id=?", (nid, t.profile_id))
    return {"ok": True}


# ---------- корзина и заказы ----------

@app.get("/api/cart")
def cart(t: auth.Token = Depends(me)):
    db = get_db()
    r = db.one("SELECT * FROM carts WHERE profile_id=?", (t.profile_id,))
    orders = [dict(o) | {"items": loads(o["items"], [])} for o in
              db.q("SELECT * FROM orders WHERE profile_id=? ORDER BY id DESC LIMIT 50", (t.profile_id,))]
    shops = [{"id": s.id, "title": s.title, "kind": s.kind} for s in order_skill.SHOPS]
    return {"cart": {"shop": r["shop"], "items": loads(r["items"], [])} if r else None, "orders": orders, "shops": shops}


class CartIn(BaseModel):
    shop: str
    items: list[dict]


@app.put("/api/cart")
def cart_put(p: CartIn, t: auth.Token = Depends(me)):
    s = session_for(t)
    from ..skills.base import Ctx
    ctx = Ctx(s)
    order_skill.save_cart(ctx, order_skill.shop_by_id(p.shop),
                          [order_skill.Item(**{k: i[k] for k in ("name", "qty", "unit") if k in i}) for i in p.items])
    return {"ok": True}


@app.post("/api/cart/checkout")
async def cart_checkout(t: auth.Token = Depends(me)):
    s = session_for(t)
    from ..skills.base import Ctx
    r = await s.call_tool(Ctx(s, user_text="оформи заказ"), "order.checkout", {}, origin="rule")
    return {"ok": r.ok, "say": r.say}


# ---------- почта ----------

class MailAcc(BaseModel):
    address: str
    password: str
    host: str = ""


@app.get("/api/mail/accounts")
def mail_accounts(t: auth.Token = Depends(me)):
    return [{k: v for k, v in dict(r).items() if k != "secret_ref"}
            for r in get_db().q("SELECT * FROM mail_accounts WHERE profile_id=?", (t.profile_id,))]


@app.post("/api/mail/accounts")
async def mail_add(p: MailAcc, t: auth.Token = Depends(me)):
    try:
        aid = await asyncio.to_thread(mail_skill.connect_account, get_db(), t.profile_id, "imap",
                                      p.address.strip(), p.password, p.host.strip())
    except Exception as e:  # noqa: BLE001
        err(Exception(f"Не удалось войти: {e}"))
    journal.log(get_db(), t.profile_id, skill="mail", tool="mail.connect", risk="local", status="done",
                summary=f"Подключён ящик {p.address}")
    return {"id": aid}


class GmailAcc(BaseModel):
    address: str
    client_id: str
    client_secret: str


@app.post("/api/mail/gmail")
async def mail_gmail(p: GmailAcc, t: auth.Token = Depends(me)):
    import webbrowser
    from ..skills import mail_conn
    try:
        cred = await asyncio.to_thread(mail_conn.gmail_oauth, p.client_id, p.client_secret, webbrowser.open)
        aid = await asyncio.to_thread(mail_skill.connect_account, get_db(), t.profile_id, "gmail",
                                      p.address.strip(), json.dumps(cred))
    except Exception as e:  # noqa: BLE001
        err(Exception(f"Gmail: {e}"))
    return {"id": aid}


@app.delete("/api/mail/accounts/{aid}")
def mail_del(aid: int, t: auth.Token = Depends(me)):
    mail_skill.remove_account(get_db(), t.profile_id, aid)
    return {"ok": True}


@app.get("/api/mail/moves")
def mail_moves(t: auth.Token = Depends(me)):
    return [dict(r) for r in get_db().q("SELECT * FROM mail_moves WHERE profile_id=? ORDER BY id DESC LIMIT 300",
                                        (t.profile_id,))]


# ---------- документы (RAG) ----------

@app.get("/api/docs")
def docs(t: auth.Token = Depends(me)):
    return [dict(r) for r in get_db().q(
        "SELECT d.*, (SELECT count(*) FROM rag_chunks c WHERE c.doc_id=d.id) AS chunks FROM rag_docs d "
        "WHERE profile_id=? ORDER BY id DESC", (t.profile_id,))]


@app.post("/api/docs")
async def doc_add(file: UploadFile = File(...), t: auth.Token = Depends(me)):
    s = session_for(t)
    from ..skills.base import Ctx
    tmp = config.HOME / "upload" / Path(file.filename or "doc.txt").name
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(await file.read())
    try:
        text = await asyncio.to_thread(knowledge.read_file, tmp)
        did = await knowledge.add_document(Ctx(s), tmp.name, text, str(tmp))
    except Exception as e:  # noqa: BLE001
        err(e)
    finally:
        tmp.unlink(missing_ok=True)
    journal.log(get_db(), t.profile_id, skill="knowledge", tool="doc.add", risk="local", status="done",
                summary=f"Добавлен документ «{tmp.name}»")
    return {"id": did}


@app.delete("/api/docs/{did}")
def doc_del(did: int, t: auth.Token = Depends(me)):
    get_db().run("DELETE FROM rag_docs WHERE id=? AND profile_id=?", (did, t.profile_id))
    return {"ok": True}


# ---------- датасет для дообучения ----------

@app.get("/api/dataset")
def dataset(t: auth.Token = Depends(me)):
    rows = get_db().q("SELECT messages FROM dataset WHERE profile_id=? ORDER BY id", (t.profile_id,))
    body = "\n".join(json.dumps({"messages": loads(r["messages"], [])}, ensure_ascii=False) for r in rows)
    return Response(body, media_type="application/jsonl",
                    headers={"Content-Disposition": "attachment; filename=jarvis-dataset.jsonl"})


@app.delete("/api/dataset")
def dataset_clear(t: auth.Token = Depends(me)):
    get_db().run("DELETE FROM dataset WHERE profile_id=?", (t.profile_id,))
    return {"ok": True}


# ---------- мастер первого запуска ----------

@app.get("/api/setup/check")
async def setup_check(t: auth.Token = Depends(me)):
    from ..voice.tts import PIPER_VOICES, piper_paths
    s = session_for(t)
    alive = await engines.ollama.alive()
    models = await engines.ollama.models() if alive else []
    wroot = config.MODELS / "whisper"
    whisper = sorted({p.name.split("--")[-1].replace("faster-whisper-", "") for p in wroot.glob("models--*")}) \
        if wroot.exists() else []
    return {"hw": hw_detect(), "ollama": alive, "llm_models": models, "whisper_models": whisper,
            "voices": {v: piper_paths(v)[0].exists() for v in PIPER_VOICES}, "engines": engines.status,
            "settings": s.settings.all()}


def _sse(gen):
    async def stream():
        try:
            async for item in gen:
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: {\"done\": true}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")


class PullReq(BaseModel):
    name: str


@app.post("/api/setup/pull")
async def setup_pull(p: PullReq, t: auth.Token = Depends(me)):
    """Скачивание модели Ollama — сеть только по нажатию кнопки в мастере."""
    async def gen():
        async for st in engines.ollama.pull(p.name):
            yield {"status": st.get("status", ""), "completed": st.get("completed", 0), "total": st.get("total", 0)}
        await engines.check_llm(session_for(t).settings.get("llm_model"))
    return _sse(gen())


@app.post("/api/setup/voice")
async def setup_voice(p: PullReq, t: auth.Token = Depends(me)):
    from ..voice.tts import PIPER_VOICES, piper_paths
    if p.name not in PIPER_VOICES:
        raise HTTPException(400, "нет такого голоса")
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/" + PIPER_VOICES[p.name] + "/" + p.name

    async def gen():
        onnx, cfg = piper_paths(p.name)
        onnx.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(follow_redirects=True, timeout=None) as c:
            for url, dest in ((base + ".onnx.json", cfg), (base + ".onnx", onnx)):
                async with c.stream("GET", url) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0))
                    got = 0
                    part = dest.with_suffix(dest.suffix + ".part")
                    with part.open("wb") as f:
                        async for b in r.aiter_bytes(1 << 16):
                            f.write(b)
                            got += len(b)
                            yield {"status": dest.name, "completed": got, "total": total}
                    part.replace(dest)
        engines.load_voice(session_for(t).settings.all())
    return _sse(gen())


@app.post("/api/setup/whisper")
async def setup_whisper(p: PullReq, t: auth.Token = Depends(me)):
    async def gen():
        from faster_whisper.utils import download_model
        yield {"status": f"скачиваю whisper {p.name}…", "completed": 0, "total": 0}
        await asyncio.to_thread(download_model, p.name, cache_dir=str(config.MODELS / "whisper"))
        yield {"status": "готово", "completed": 1, "total": 1}
        s = session_for(t)
        s.settings.set("whisper_model", p.name)
        engines.load_voice(s.settings.all())
    return _sse(gen())


# ---------- WebSocket ----------

@app.websocket("/ws")
async def ws(sock: WebSocket):
    host = (sock.headers.get("host") or "").split(":")[0]
    if host not in ALLOWED_HOSTS or (config.LAUNCH_SECRET and sock.query_params.get("s") != config.LAUNCH_SECRET):
        await sock.close(code=4403)
        return
    try:
        t = auth.check(sock.query_params.get("token"))
    except auth.AuthError:
        await sock.close(code=4401)
        return
    await sock.accept()
    s = session_for(t)
    send_lock = asyncio.Lock()

    async def send_json(msg: dict):
        async with send_lock:
            await sock.send_text(json.dumps(msg, ensure_ascii=False, default=str))

    async def send_bytes(data: bytes):
        async with send_lock:
            await sock.send_bytes(data)

    pair = s.attach(send_json, send_bytes)
    await send_json({"type": "hello", "profile": {"id": t.profile_id, "name": t.name},
                     "settings": s.settings.all(), "engines": engines.status, "llm": engines.llm_ok,
                     "timers": s.list_timers(), **{"status": s.status_payload()}})
    try:
        while True:
            msg = await sock.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if (data := msg.get("bytes")) is not None:
                s.feed_audio(data)
                continue
            try:
                m = json.loads(msg.get("text") or "{}")
            except ValueError:
                continue
            await handle_ws(s, m)
    except WebSocketDisconnect:
        pass
    finally:
        s.detach(pair)


async def handle_ws(s: Session, m: dict) -> None:
    kind = m.get("type")
    if kind == "text":
        text = str(m.get("text", ""))[:2000]
        await s.handle_utterance(text, source="text")
    elif kind == "confirm":
        s.resolve_confirm(str(m.get("id")), bool(m.get("ok")))
    elif kind == "stop":
        await s.shut_up()
        if s.turn and not s.turn.done():
            s.turn.cancel()
        s.busy = False
        await s.idle()
    elif kind == "mic":
        if m.get("on"):
            s.mic_start()
        else:
            s.mic_stop()
        await s.idle()
    elif kind == "playback":
        await s.playback_state(bool(m.get("playing")))
    elif kind == "engines":
        await s.emit({"type": "engines", "engines": engines.status, "llm": engines.llm_ok})
    elif kind == "ping":
        await s.emit({"type": "pong", "t": m.get("t")})
