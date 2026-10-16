"""Versioned service API and transactional SQLite change stream."""
import hmac
import json
import time
from flask import jsonify, request
from sqlalchemy import text
from . import config, db, runs, service, audit
from .models import Job, SearchRun, SearchTask, Setting


def init_journal():
    # SQLite triggers cover UI, CLI, bulk updates and deletions in the same transaction.
    columns = [c.name for c in Job.__table__.columns if c.name not in ("raw", "embedding")]
    def payload(prefix):
        return "json_object(" + ",".join(f"'{c}',{prefix}.{c}" for c in columns) + "," + (
            "'search_ids',json(COALESCE((SELECT json_group_array(task_id) FROM task_jobs WHERE job_id="+prefix+".id),'[]')),"
            "'run_ids',json(COALESCE((SELECT json_group_array(DISTINCT t.run_id) FROM task_jobs l JOIN search_tasks t ON t.id=l.task_id WHERE l.job_id="+prefix+".id),'[]')))"
        )
    with db.engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS job_changes (sequence INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, operation TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
        for event, prefix in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            operation = "'delete'" if event == "DELETE" else f"CASE WHEN {prefix}.deleted_at IS NOT NULL OR {prefix}.quality_ok=0 THEN 'delete' ELSE 'upsert' END"
            conn.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS jobs_journal_{event.lower()} AFTER {event} ON jobs BEGIN INSERT INTO job_changes(job_id,operation,payload) VALUES ({prefix}.id,{operation},{payload(prefix)}); END")
        conn.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS task_jobs_journal AFTER INSERT ON task_jobs BEGIN INSERT INTO job_changes(job_id,operation,payload) SELECT j.id, CASE WHEN j.deleted_at IS NOT NULL OR j.quality_ok=0 THEN 'delete' ELSE 'upsert' END,"+payload("j")+" FROM jobs j WHERE j.id=NEW.job_id; END")
        marker = conn.execute(text("SELECT value FROM settings WHERE key='service_journal_initialized' ")).first()
        if not marker:
            conn.exec_driver_sql("INSERT INTO job_changes(job_id,operation,payload) SELECT j.id, CASE WHEN j.deleted_at IS NOT NULL OR j.quality_ok=0 THEN 'delete' ELSE 'upsert' END,"+payload("j")+" FROM jobs j ORDER BY j.id")
            conn.exec_driver_sql("INSERT INTO settings(key,value) VALUES ('service_journal_initialized','1')")


def integer(name, default, maximum=None):
    raw = request.args.get(name, str(default))
    if not raw.isascii() or not raw.isdigit():
        raise ValueError(f"{name} pozitif tam sayı veya sıfır olmalı.")
    value = int(raw)
    if maximum and not 1 <= value <= maximum:
        raise ValueError(f"{name}: 1–{maximum} aralığında olmalı.")
    return value


def install(server):
    app = server.app

    @app.get('/api/service/status')
    def service_status():
        from .transport import Coordinator
        from sqlalchemy import func
        with server.SessionLocal() as session:
            scheduled = session.query(SearchRun).filter(SearchRun.deleted_at.is_(None),
                func.json_extract(SearchRun.options,'$.schedule_enabled') == 1,
                func.json_extract(SearchRun.options,'$.schedule_dispatched').is_(None)).order_by(SearchRun.created_at.desc()).limit(100).all()
            return jsonify(supervisor_alive=bool(service.supervisor and service.supervisor.is_alive()),
                heartbeat_at=service.heartbeat, last_error=service.last_error, source=Coordinator().state(),
                api_key_configured=bool(config.API_KEY), admin_key_configured=bool(config.ADMIN_KEY),
                schedules=[dict(run_id=r.id,status=r.status,repeat_seconds=json.loads(r.options)['repeat_seconds'],
                    keywords=[t.keyword for t in session.query(SearchTask).filter_by(run_id=r.id)]) for r in scheduled])

    @app.post('/api/service/schedules/<run_id>/stop')
    @app.post('/api/v1/collections/<run_id>/disable-schedule')
    def disable_schedule(run_id):
        with runs.lock, server.SessionLocal() as session:
            root = session.get(SearchRun,run_id)
            if not root:
                return jsonify(error='Bulunamadı.'),404
            identifiers = {run_id}
            all_runs = session.query(SearchRun).all()
            while True:
                descendants = {r.id for r in all_runs if json.loads(r.options or '{}').get('parent_run_id') in identifiers}
                if descendants.issubset(identifiers):
                    break
                identifiers |= descendants
            for run in all_runs:
                if run.id not in identifiers:
                    continue
                options = json.loads(run.options or '{}')
                options['schedule_enabled'] = False
                if run.status == 'queued' and options.get('service_managed'):
                    options['service_managed'] = False
                    runs.transition(run,'cancelled','Tekrarlı toplama kapatıldı.')
                    for task in session.query(SearchTask).filter_by(run_id=run.id):
                        runs.transition(task,'cancelled',run.status_reason)
                run.options = json.dumps(options)
                audit.record(session,run.id,None,'schedule_disabled',{'root_run_id':run_id})
            session.commit()
        return jsonify(ok=True)

    @app.before_request
    def authorize():
        if request.path == '/healthz':
            return None
        origin = request.headers.get('Origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc != request.host:
                return jsonify(error='Bu kaynaktan yönetim isteği kabul edilmiyor.'),403
        versioned = request.path.startswith('/api/v1/')
        external = request.remote_addr not in ('127.0.0.1', '::1', None)
        if not versioned and not external:
            return None
        if not (versioned or request.path.startswith('/api/') or request.path == '/events'):
            return None
        supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
        allowed = [config.ADMIN_KEY] if request.method != 'GET' or not versioned else [config.API_KEY, config.ADMIN_KEY]
        if not any(key and hmac.compare_digest(supplied, key) for key in allowed):
            return jsonify(error='Geçerli Bearer anahtarı gerekli.', code='unauthorized'), 401

    @app.get('/healthz')
    def health():
        try:
            with server.SessionLocal() as session:
                session.execute(text('SELECT 1'))
            alive = bool(service.supervisor and service.supervisor.is_alive())
            healthy = alive and time.time()-service.heartbeat < max(30, config.SERVICE_POLL_SECONDS*3) and not service.last_error
            return jsonify(status='ok' if healthy else 'degraded', database='ok', collector=alive), 200 if healthy else 503
        except Exception:
            return jsonify(status='unavailable', database='error'), 503

    @app.get('/api/v1/status')
    def status():
        from .transport import Coordinator
        return jsonify(api_version='1', running=server.state.running, run_id=server.state.run_id,
            source=Coordinator().state(), supervisor_alive=bool(service.supervisor and service.supervisor.is_alive()),
            heartbeat_at=service.heartbeat, last_error=service.last_error)

    @app.get('/api/v1/jobs')
    def jobs():
        after, limit = integer('after_id', 0), integer('limit', 100, 500)
        with server.SessionLocal() as session:
            query = session.query(Job).filter(Job.id > after, Job.deleted_at.is_(None), Job.quality_ok.is_(True))
            for key in ('source', 'category', 'company', 'location'):
                if request.args.get(key):
                    query = query.filter(getattr(Job, key) == request.args[key])
            rows = query.order_by(Job.id).limit(limit+1).all()
            return jsonify(items=[j.to_dict(include_description=True) for j in rows[:limit]],
                next_after_id=rows[min(limit,len(rows))-1].id if rows else after, has_more=len(rows)>limit)

    @app.get('/api/v1/jobs/changes')
    def changes():
        after, limit = integer('after', 0), integer('limit', 100, 500)
        with server.SessionLocal() as session:
            rows = session.execute(text('SELECT * FROM job_changes WHERE sequence>:after ORDER BY sequence LIMIT :limit'), {'after':after,'limit':limit+1}).mappings().all()
            items = []
            for row in rows[:limit]:
                data = json.loads(row['payload'])
                for key in ('tags', 'offerings'):
                    data[key] = json.loads(data[key] or '[]')
                data['quality_ok'] = bool(data['quality_ok'])
                items.append(dict(sequence=row['sequence'], operation=row['operation'], job_id=row['job_id'],
                    changed_at=row['created_at'], job=data if row['operation']=='upsert' else None))
            return jsonify(items=items, next_cursor=items[-1]['sequence'] if items else after, has_more=len(rows)>limit)

    @app.post('/api/v1/collections')
    def collect():
        from .enhanced import task_data, scrape_options
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise ValueError('İstek gövdesi JSON nesnesi olmalı.')
        tasks = task_data(body)
        repeat = body.get('repeat_seconds', 0)
        if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat and repeat < 900:
            raise ValueError('repeat_seconds sıfır veya en az 900 saniye olmalı.')
        backend = body.get('classify_backend', 'rules')
        if backend not in ('rules', 'local', 'claude'):
            raise ValueError('Geçersiz analiz yöntemi.')
        key = request.headers.get('Idempotency-Key', '')
        if not key or len(key)>128:
            raise ValueError('1–128 karakterlik Idempotency-Key gerekli.')
        import hashlib
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        marker = 'collection:' + hashlib.sha256(key.encode()).hexdigest()[:48]
        with runs.lock, server.SessionLocal() as session:
            previous = session.get(Setting, marker)
            if previous:
                saved = json.loads(previous.value)
                if saved['digest'] != digest:
                    return jsonify(error='Aynı Idempotency-Key farklı istekle kullanılamaz.'), 409
                return jsonify(run_id=saved['run_id'], replay=True), 200
            run_id = runs.identifier()
            options = dict(kind='scrape', service_managed=True, schedule_enabled=bool(repeat), repeat_seconds=repeat,
                classify_backend=backend, use_embeddings=bool(body.get('use_embeddings')), **scrape_options(body))
            session.add(SearchRun(id=run_id, options=json.dumps(options)))
            for i, task in enumerate(tasks):
                if session.get(SearchTask, task['id']):
                    raise ValueError('Görev kimliği zaten kullanımda.')
                session.add(SearchTask(run_id=run_id, position=i, **task))
                audit.record(session, run_id, task['id'], 'task_queued', task)
            session.add(Setting(key=marker, value=json.dumps(dict(digest=digest,run_id=run_id))))
            audit.record(session, run_id, None, 'run_created', {'actor':'service_api','options':options})
            session.commit()
        return jsonify(run_id=run_id, replay=False), 202

    @app.get('/api/v1/collections/<run_id>')
    def collection(run_id):
        with server.SessionLocal() as session:
            run = session.get(SearchRun, run_id)
            if not run or run.deleted_at:
                return jsonify(error='Bulunamadı.'), 404
            result = runs.snapshot(session, run)
            opts = json.loads(run.options or '{}')
            result['schedule'] = {key:opts.get(key) for key in ('schedule_enabled','repeat_seconds','schedule_dispatched','parent_run_id','auto_resume_at')}
            return jsonify(result)

    @app.post('/api/v1/collections/<run_id>/<action>')
    def control(run_id, action):
        if action not in ('pause', 'resume', 'stop', 'cancel'):
            raise ValueError('Geçersiz işlem.')
        return app.view_functions['run_action'](run_id, action)
