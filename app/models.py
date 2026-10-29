from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    password_plain = db.Column(db.String(256))
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    role = db.Column(db.String(20), default='user')
    can_report = db.Column(db.Boolean, default=False)
    can_data = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    equipments = db.relationship('Equipment', backref='owner', lazy='dynamic')
    projects = db.relationship('Project', backref='owner', lazy='dynamic')
    employees = db.relationship('Employee', backref='owner', lazy='dynamic')
    operations = db.relationship('Operation', backref='owner', lazy='dynamic')
    def set_password(self, password, keep_plain=True):
        self.password_hash = generate_password_hash(password)
        if keep_plain:
            self.password_plain = password
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    @property
    def is_admin(self):
        return self.role == 'admin'
    @property
    def can_use_report(self):
        return self.is_admin or bool(self.can_report)
    @property
    def can_use_data(self):
        return self.is_admin or bool(self.can_data)

class Employee(db.Model):
    __tablename__ = 'employees'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    position = db.Column(db.String(100))
    phone = db.Column(db.String(30))
    # 'own' - сотрудник нашего отдела (выдаёт/принимает); 'other' - сотрудник другого отдела (кому выдали / от кого приняли)
    kind = db.Column(db.String(10), default='own')
    department = db.Column(db.String(120))

class Project(db.Model):
    __tablename__ = 'projects'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    equipments = db.relationship('Equipment', backref='project', lazy=True)
    kits = db.relationship('Kit', backref='project', cascade='all, delete-orphan', lazy=True)

class Kit(db.Model):
    __tablename__ = 'kits'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    equipments = db.relationship('Equipment', backref='kit', lazy=True)

class Equipment(db.Model):
    __tablename__ = 'equipments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60))
    decimal_number = db.Column(db.String(100))
    serial_number = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(80), default='На складе')
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=True)
    kit_id = db.Column(db.Integer, db.ForeignKey('kits.id'), nullable=True)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    received_from = db.Column(db.String(255))
    acceptance_report = db.Column(db.String(500))
    photo_path = db.Column(db.String(500))
    status_before_archive = db.Column(db.String(80))
    photos = db.relationship('EquipmentPhoto', backref='equipment', cascade='all, delete-orphan', lazy=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    operation_items = db.relationship('OperationItem', backref='equipment', lazy=True)

class Operation(db.Model):
    __tablename__ = 'operations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    op_type = db.Column(db.String(20), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    employee = db.relationship('Employee', foreign_keys=[employee_id])
    issuer_employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    issuer = db.relationship('Employee', foreign_keys=[issuer_employee_id])
    # Free-text counterparty: "Кому выдано" (issue) / "От кого принято" (receive).
    # Not an Employee - the staff directory only holds who issues/accepts.
    recipient_name = db.Column(db.String(255))
    seq_number = db.Column(db.Integer)
    @property
    def party_name(self):
        return self.recipient_name or (self.employee.full_name if self.employee else None)
    @property
    def party_full(self):
        # Имя + отдел (для подробного просмотра операции)
        name = self.party_name
        if not name:
            return None
        key = name.strip().casefold()
        for emp in Employee.query.filter_by(user_id=self.user_id).all():
            if emp.full_name.strip().casefold() == key:
                if (emp.kind or 'own') == 'own':
                    return name
                return f'{name} ({emp.department})' if emp.department else f'{name} (Отдел не указан)'
        return f'{name} (Отдел не указан)'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    comment = db.Column(db.Text)
    items = db.relationship('OperationItem', backref='operation', cascade="all, delete-orphan")

class OperationItem(db.Model):
    __tablename__ = 'operation_items'
    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey('operations.id'), nullable=False)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipments.id'), nullable=False)


class EquipmentPhoto(db.Model):
    __tablename__ = 'equipment_photos'
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipments.id'), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
