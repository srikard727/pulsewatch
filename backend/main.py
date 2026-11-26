import os, time, socket, ipaddress
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, Field
from sqlalchemy import create_engine, String, Integer, Float, DateTime, ForeignKey, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from celery import Celery
import httpx

engine = create_engine(os.getenv('DATABASE_URL', 'sqlite:///pulsewatch.db'), pool_pre_ping=True)
class Base(DeclarativeBase): pass
class Monitor(Base):
    __tablename__ = 'monitors'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(2048))
    interval: Mapped[int] = mapped_column(Integer)
    retries: Mapped[int] = mapped_column(Integer)
    next_check: Mapped[datetime] = mapped_column(DateTime(timezone=True))
class Check(Base):
    __tablename__ = 'checks'
    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey('monitors.id', ondelete='CASCADE'), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)

def now(): return datetime.now(timezone.utc)
def validate_target(url):
    p = urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443):
        raise ValueError('Only public HTTP(S) endpoints on standard ports are allowed')
    for entry in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme=='https' else 80), type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(entry[4][0]).is_global: raise ValueError('Non-public destination')

def probe(url, retries):
    for attempt in range(retries+1):
        start = time.monotonic(); status = None; error = None
        try:
            validate_target(url)
            with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
                with client.stream('GET', url) as response: status = response.status_code
            if not 200 <= status < 300: error = 'Unexpected HTTP status'
        except (httpx.HTTPError, OSError, ValueError) as exc: error = type(exc).__name__
        latency = (time.monotonic()-start)*1000
        if error is None: break
        if attempt < retries: time.sleep(1)
    return dict(status=status, latency_ms=round(latency,2), error=error)

celery = Celery('pulsewatch', broker=os.getenv('REDIS_URL','redis://localhost:6379/0'))
celery.conf.update(beat_schedule={'dispatch': {'task':'main.dispatch','schedule':10.0}}, task_ignore_result=True, broker_connection_retry_on_startup=True)
@celery.task
def dispatch():
    with Session(engine) as db:
        due = db.scalars(select(Monitor).where(Monitor.next_check <= now()).with_for_update(skip_locked=True)).all()
        for m in due:
            run_check.delay(m.id)
            m.next_check = now()+timedelta(seconds=m.interval)
        db.commit()
@celery.task
def run_check(mid):
    with Session(engine) as db:
        m = db.get(Monitor,mid)
        if not m: return
        result = probe(m.url,m.retries)
        db.add(Check(monitor_id=mid,checked_at=now(),**result)); db.commit()

app = FastAPI(title='PulseWatch')
class MonitorInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    url: HttpUrl
    interval: int = Field(default=60,ge=30,le=86400)
    retries: int = Field(default=1,ge=0,le=2)
@app.get('/health')
def health(): return {'status':'ok'}
@app.post('/monitors',status_code=201)
def create(data: MonitorInput):
    try: validate_target(str(data.url))
    except (ValueError,OSError) as exc: raise HTTPException(422,'Invalid or non-public endpoint') from exc
    with Session(engine) as db:
        m=Monitor(**data.model_dump(exclude={'url'}),url=str(data.url),next_check=now()); db.add(m); db.commit(); db.refresh(m); return m
@app.get('/monitors')
def monitors():
    with Session(engine) as db:
        result=[]
        for m in db.scalars(select(Monitor).order_by(Monitor.id)):
            recent=select(Check).where(Check.monitor_id==m.id,Check.checked_at>=now()-timedelta(days=1))
            total=db.scalar(select(func.count()).select_from(recent.subquery()))
            good=db.scalar(select(func.count()).select_from(recent.where(Check.error.is_(None)).subquery()))
            last=db.scalar(select(Check).where(Check.monitor_id==m.id).order_by(Check.id.desc()).limit(1))
            result.append(dict(id=m.id,name=m.name,url=m.url,interval=m.interval,uptime=round(100*good/total,2) if total else None,last=last))
        return result
@app.get('/monitors/{mid}/checks')
def history(mid:int):
    with Session(engine) as db:
        if not db.get(Monitor,mid): raise HTTPException(404)
        return list(db.scalars(select(Check).where(Check.monitor_id==mid).order_by(Check.id.desc()).limit(100)))
@app.delete('/monitors/{mid}',status_code=204)
def delete(mid:int):
    with Session(engine) as db:
        m=db.get(Monitor,mid)
        if not m: raise HTTPException(404)
        db.query(Check).filter_by(monitor_id=mid).delete(); db.delete(m); db.commit()
