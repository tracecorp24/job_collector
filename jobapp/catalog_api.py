"""Small, shared listing catalog. Descriptions are requested only for one job."""
import gzip
import json
import threading
import time
from flask import Response, jsonify, request
from sqlalchemy import func, text
from .models import Job

_lock = threading.Lock()
_cache = {}
_preview_cache = {}
_preview_lock = threading.Lock()
FIELDS = ('id', 'source', 'external_id', 'title', 'company', 'location',
          'location_country', 'location_city', 'workplace_type', 'category',
          'seniority', 'tags', 'salary', 'salary_min', 'salary_max',
          'salary_currency', 'posted_at', 'scraped_at', 'experience_years',
          'url', 'opportunity_type', 'internship_details', 'profession_groups',
          'profession_subgroups')


def register(app, server):
    def revision(session):
        return str(session.execute(text('SELECT COALESCE(MAX(sequence),0) FROM job_changes')).scalar())

    @app.get('/api/v1/jobs/revision')
    def catalog_revision():
        with server.SessionLocal() as session:
            return jsonify(token=revision(session))

    @app.get('/api/v1/jobs/catalog')
    def catalog():
        started = time.monotonic()
        preview = request.args.get('limit') == '50'
        with server.SessionLocal() as session:
            token = revision(session)
            with (_preview_lock if preview else _lock):
                identity = (server.SessionLocal, token)
                selected_cache = _preview_cache if preview else _cache
                if selected_cache.get('identity') != identity:
                    columns = [getattr(Job, f) for f in FIELDS]
                    query = session.query(*columns).filter(Job.deleted_at.is_(None), Job.quality_ok.is_(True),
                        func.coalesce(Job.flag, '').notin_(('scam', 'ghost')))
                    total = query.with_entities(func.count(Job.id)).scalar() if preview else None
                    ordered = query.order_by(Job.id.desc())
                    rows = ordered.limit(50).all() if preview else ordered.all()
                    items = []
                    for row in rows:
                        item = dict(zip(FIELDS, row))
                        item['country'] = item.pop('location_country')
                        item['city'] = item.pop('location_city')
                        for name, default in [('tags', []), ('internship_details', {}), ('profession_groups', []), ('profession_subgroups', [])]:
                            try: item[name] = json.loads(item[name] or json.dumps(default))
                            except (ValueError, TypeError): item[name] = default
                        for name in ('posted_at', 'scraped_at'):
                            item[name] = item[name].isoformat() if item[name] else None
                        items.append(item)
                    payload = json.dumps(dict(items=items, token=token, total=total if preview else len(items)), ensure_ascii=False,
                                         separators=(',', ':')).encode()
                    selected_cache.clear()
                    selected_cache.update(identity=identity, payload=payload, gzip=gzip.compress(payload, compresslevel=5, mtime=0))
                payload = selected_cache['gzip'] if 'gzip' in request.accept_encodings else selected_cache['payload']
        response = Response(payload, mimetype='application/json')
        if 'gzip' in request.accept_encodings: response.headers['Content-Encoding'] = 'gzip'
        response.headers['Vary'] = 'Accept-Encoding'
        response.headers['Server-Timing'] = f'catalog;dur={(time.monotonic()-started)*1000:.1f}'
        return response

    @app.get('/api/v1/jobs/detail/<source>/<external_id>')
    def detail(source, external_id):
        with server.SessionLocal() as session:
            job = session.query(Job).filter_by(source=source, external_id=external_id,
                deleted_at=None, quality_ok=True).first()
            if not job or job.flag in ('scam', 'ghost'):
                return jsonify(error='İlan bulunamadı.'), 404
            return jsonify(item=job.to_dict(include_description=True))

    @app.get('/api/v1/jobs/search-ids')
    def search_ids():
        # Bound query input; SQLAlchemy binds every search term as a parameter.
        query = request.args.get('q', '').strip()[:200]
        if not query: return jsonify(ids=[])
        from sqlalchemy import or_
        from .search_engine import build_search_filter, search_fold
        from .search_text import contains
        with server.SessionLocal() as session:
            f_q = search_fold(query)
            base_filter = build_search_filter(Job, query)
            desc_filter = Job.description.ilike(f'%{f_q}%') if f_q.isascii() else contains(Job.description, f_q)
            search_clause = or_(base_filter, desc_filter) if base_filter is not None else desc_filter
            rows = session.query(Job.source, Job.external_id).filter(
                Job.deleted_at.is_(None),
                Job.quality_ok.is_(True),
                func.coalesce(Job.flag, '').notin_(('scam', 'ghost')),
                search_clause
            ).limit(250).all()
            return jsonify(ids=[f'{source}-{external_id}' for source, external_id in rows])
