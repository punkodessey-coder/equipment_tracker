import os, sqlite3, secrets
from flask import Flask, request, redirect, url_for, flash
from flask_login import current_user
from app.extensions import db, login_manager
from app.models import User, Project, Equipment

def _ensure_schema(app):
    with app.app_context():
        db.create_all()
        engine = db.engine
        if engine.url.get_backend_name() != 'sqlite':
            return
        path = engine.url.database
        if not path or path == ':memory:':
            return
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        additions = {
            'users': [
                ('password_plain', 'VARCHAR(256)'), ('must_change_password', 'BOOLEAN DEFAULT 0'),
                ('can_report', 'BOOLEAN DEFAULT 0'), ('can_data', 'BOOLEAN DEFAULT 0')
            ],
            'projects': [('archived', 'BOOLEAN DEFAULT 0')],
            'employees': [('kind', "VARCHAR(10) DEFAULT 'own'"), ('department', 'VARCHAR(120)')],
            'operations': [('recipient_name','VARCHAR(255)'), ('seq_number','INTEGER')],
            'equipment_photos': [('equipment_id','INTEGER'), ('filename','VARCHAR(500)'), ('created_at','DATETIME')],
            'equipments': [
                ('decimal_number','VARCHAR(100)'), ('kit_id','INTEGER'),
                ('received_at','DATETIME'), ('received_from','VARCHAR(255)'),
                ('acceptance_report','VARCHAR(500)'), ('photo_path','VARCHAR(500)'),
                ('status_before_archive','VARCHAR(80)')
            ]
        }
        new_cols = set()
        for table, cols in additions.items():
            if table not in tables:
                continue
            existing = {r[1] for r in cur.execute(f'PRAGMA table_info("{table}")')}
            for name, typ in cols:
                if name not in existing:
                    cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {typ}')
                    new_cols.add((table, name))
        conn.commit()
        conn.close()
        # Однократное заполнение при добавлении новых колонок.
        if ('employees', 'kind') in new_cols:
            from app.models import Employee, Operation
            db.session.query(Employee).filter(Employee.kind.is_(None)).update({Employee.kind: 'own'}, synchronize_session=False)
            db.session.commit()
            for uid in {o.user_id for o in Operation.query.all()}:
                known = {e.full_name.strip().casefold() for e in Employee.query.filter_by(user_id=uid).all()}
                for o in Operation.query.filter_by(user_id=uid).order_by(Operation.created_at, Operation.id).all():
                    nm = (o.party_name or '').strip()
                    if nm and nm.casefold() not in known:
                        db.session.add(Employee(user_id=uid, full_name=nm, kind='other')); known.add(nm.casefold())
            db.session.commit()
        from app.models import Operation as _Op
        for uid in {o.user_id for o in _Op.query.filter(_Op.seq_number.is_(None)).all()}:
            top = db.session.query(db.func.max(_Op.seq_number)).filter(_Op.user_id == uid).scalar() or 0
            for o in _Op.query.filter(_Op.user_id == uid, _Op.seq_number.is_(None)).order_by(_Op.created_at, _Op.id).all():
                top += 1; o.seq_number = top
        db.session.commit()
        # Backfill initial receipt time for existing equipment.
        for eq in Equipment.query.filter(Equipment.received_at.is_(None)).all():
            eq.received_at = eq.created_at
        db.session.query(Project).filter(Project.archived.is_(None)).update({Project.archived: False}, synchronize_session=False)
        legacy_admin = User.query.filter_by(username='admin').first()
        if legacy_admin and not legacy_admin.password_plain:
            legacy_admin.password_plain = 'admin123'
        db.session.commit()

def _load_or_create_secret_key():
    # A hardcoded key would let anyone who reads the source forge login
    # sessions - generate one per install and persist it instead.
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    instance_dir = os.path.join(base, 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    key_path = os.path.join(instance_dir, 'secret_key.txt')
    if os.path.exists(key_path):
        key = open(key_path, encoding='utf-8').read().strip()
        if key:
            return key
    key = secrets.token_hex(32)
    with open(key_path, 'w', encoding='utf-8') as f:
        f.write(key)
    return key

def create_app():
    app = Flask(__name__,
                template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates')),
                static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static')))
    app.config['SECRET_KEY'] = _load_or_create_secret_key()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///equipment.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_connect_url():
        from app.routes.main import connect_url
        return {'connect_url': connect_url()}

    @app.before_request
    def force_password_change():
        if not getattr(request, 'endpoint', None) or not request.endpoint:
            return
        if not current_user.is_authenticated:
            return
        if request.endpoint in {'auth.change_password', 'auth.logout', 'static', 'main.qr_svg'}:
            return
        if getattr(current_user, 'must_change_password', False):
            flash('Требуется принудительная смена пароля. Сначала смените пароль.', 'warning')
            return redirect(url_for('auth.change_password'))

    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.equipment import equipment_bp
    from app.routes.operations import operations_bp
    from app.routes.directory import directory_bp
    from app.routes.admin import admin_bp
    from app.routes.data import data_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(operations_bp)
    app.register_blueprint(directory_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(data_bp)
    @app.cli.command('upgrade-schema')
    def upgrade_schema_command():
        """Apply the legacy SQLite schema updates and data backfills."""
        _ensure_schema(app)
        print('Схема базы данных обновлена.')

    return app
