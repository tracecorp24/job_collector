"""Small, shared listing catalog. Descriptions are requested only for one job."""
import gzip
import json
import threading
import time
from flask import Response, jsonify, request
from sqlalchemy import func, text
from werkzeug.datastructures import MultiDict
from .models import Job

_lock = threading.Lock()
_cache = {}
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
        with server.SessionLocal() as session:
            token = revision(session)
            with _lock:
                identity = (server.SessionLocal, token)
                if _cache.get('identity') != identity:
                    columns = [getattr(Job, f) for f in FIELDS]
                    rows = session.query(*columns).filter(Job.deleted_at.is_(None), Job.quality_ok.is_(True),
                        func.coalesce(Job.flag, '').notin_(('scam', 'ghost'))).order_by(Job.id.desc()).all()
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
                    payload = json.dumps(dict(items=items, token=token, total=len(items)), ensure_ascii=False,
                                         separators=(',', ':')).encode()
                    _cache.clear()
                    _cache.update(identity=identity, payload=payload, gzip=gzip.compress(payload, compresslevel=5, mtime=0))
                payload = _cache['gzip'] if 'gzip' in request.accept_encodings else _cache['payload']
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
        from .filters import filtered
        with server.SessionLocal() as session:
            rows = filtered(session, MultiDict({'search': query})).filter(func.coalesce(Job.flag, '').notin_(('scam', 'ghost'))).with_entities(Job.source, Job.external_id).all()
            return jsonify(ids=[f'{source}-{external_id}' for source, external_id in rows])
