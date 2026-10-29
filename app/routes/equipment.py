import os
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models import Equipment, Project, Kit, OperationItem, EquipmentPhoto, Operation

equipment_bp = Blueprint('equipment', __name__, url_prefix='/equipment')

def sanitize_serial_number(sn):
    if not sn:
        return None
    sn_clean = sn.strip()
    if sn_clean.lower() in ['', 'n/a', 'б/н', 'нет', 'none', '-']:
        return None
    return sn_clean

def save_upload(file, prefix):
    if not file or not file.filename:
        return None
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {'.pdf', '.docx', '.jpg', '.jpeg', '.png', '.webp'}:
        return None
    name = secure_filename(f'{prefix}_{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")}{ext}')
    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], name))
    return name

@equipment_bp.route('/')
@login_required
def list_equipment():
    items = Equipment.query.filter_by(user_id=current_user.id).order_by(Equipment.name.asc()).all()
    projects = Project.query.filter_by(user_id=current_user.id, archived=False).all()
    kits = Kit.query.join(Project).filter(Project.user_id == current_user.id, Project.archived == False).all()
    return render_template('equipment/list.html', items=items, projects=projects, kits=kits)

@equipment_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_equipment():
    projects = Project.query.filter_by(user_id=current_user.id, archived=False).all()
    kits = Kit.query.join(Project).filter(Project.user_id == current_user.id, Project.archived == False).all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        decimal_number = request.form.get('decimal_number', '').strip() or None
        sn = sanitize_serial_number(request.form.get('serial_number'))
        project_id = request.form.get('project_id') or None
        kit_id = request.form.get('kit_id') or None
        received_from = request.form.get('received_from', '').strip() or None
        report = request.files.get('acceptance_report')
        photos = [f for f in request.files.getlist('photos') if f and f.filename]
        if sn and Equipment.query.filter_by(user_id=current_user.id, serial_number=sn).first():
            flash(f'Оборудование с серийным номером "{sn}" уже зарегистрировано!', 'danger')
            return render_template('equipment/form.html', projects=projects, kits=kits)
        if not name:
            flash('Укажите наименование оборудования.', 'danger')
            return render_template('equipment/form.html', projects=projects, kits=kits)
        if not project_id:
            flash('Оборудование без проекта принять нельзя.', 'danger')
            return render_template('equipment/form.html', projects=projects, kits=kits)
        if len(photos) > 20:
            flash('Можно загрузить не более 20 фотографий.', 'danger')
            return render_template('equipment/form.html', projects=projects, kits=kits)
        report_name = save_upload(report, 'acceptance') if report and report.filename else None
        photo_names = [save_upload(f, 'photo') for f in photos]
        photo_names = [x for x in photo_names if x]
        photo_name = photo_names[0] if photo_names else None
        eq = Equipment(user_id=current_user.id, name=name, category=None,
                       decimal_number=decimal_number, serial_number=sn,
                       project_id=project_id, kit_id=kit_id, status='На складе',
                       received_at=datetime.now(timezone.utc), received_from=received_from,
                       acceptance_report=report_name, photo_path=photo_name)
        db.session.add(eq); db.session.flush()
        for filename in photo_names:
            db.session.add(EquipmentPhoto(equipment_id=eq.id, filename=filename))
        db.session.commit()
        flash('Новое оборудование успешно добавлено.', 'success')
        return redirect(url_for('equipment.list_equipment'))
    return render_template('equipment/form.html', projects=projects, kits=kits)

@equipment_bp.route('/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_equipment(item_id):
    item = Equipment.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    # Проекты: активные + текущий проект позиции (если он в архиве)
    projects = [p for p in Project.query.filter_by(user_id=current_user.id).all() if not p.archived or p.id == item.project_id]
    kits = [k for k in Kit.query.join(Project).filter(Project.user_id == current_user.id).all() if not k.project.archived or k.project_id == item.project_id]
    def render():
        return render_template('equipment/form.html', projects=projects, kits=kits, item=item)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        decimal_number = request.form.get('decimal_number', '').strip() or None
        sn = sanitize_serial_number(request.form.get('serial_number'))
        project_id = request.form.get('project_id', type=int)
        kit_id = request.form.get('kit_id', type=int)
        received_from = request.form.get('received_from', '').strip() or None
        photos = [f for f in request.files.getlist('photos') if f and f.filename]
        if not name:
            flash('Укажите наименование оборудования.', 'danger'); return render()
        if not project_id or not Project.query.filter_by(id=project_id, user_id=current_user.id).first():
            flash('Укажите проект.', 'danger'); return render()
        if sn and Equipment.query.filter(Equipment.user_id == current_user.id, Equipment.serial_number == sn, Equipment.id != item.id).first():
            flash(f'Оборудование с серийным номером "{sn}" уже зарегистрировано!', 'danger'); return render()
        if kit_id and not Kit.query.filter_by(id=kit_id, project_id=project_id).first():
            kit_id = None
        if len(item.photos) + len(photos) > 20:
            flash('Можно загрузить не более 20 фотографий.', 'danger'); return render()
        photo_names = [x for x in (save_upload(f, 'photo') for f in photos) if x and os.path.splitext(x)[1].lower() in {'.jpg', '.jpeg', '.png', '.webp'}]
        item.name = name; item.decimal_number = decimal_number; item.serial_number = sn
        item.project_id = project_id; item.kit_id = kit_id; item.received_from = received_from
        for filename in photo_names:
            db.session.add(EquipmentPhoto(equipment_id=item.id, filename=filename))
        if photo_names and not item.photo_path:
            item.photo_path = photo_names[0]
        db.session.commit()
        flash('Изменения сохранены.', 'success')
        return redirect(url_for('equipment.detail', item_id=item.id))
    return render()

@equipment_bp.route('/<int:item_id>')
@login_required
def detail(item_id):
    item = Equipment.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    history = []
    for op_item in OperationItem.query.filter_by(equipment_id=item.id).all():
        op = op_item.operation
        if op.user_id == current_user.id:
            history.append({'date': op.created_at, 'op_type': op.op_type, 'op_id': op.id, 'seq': op.seq_number or op.id,
                'recipient': op.party_name or '—',
                'issuer': op.issuer.full_name if op.issuer else '—', 'comment': op.comment})
    history.sort(key=lambda x: x['date'], reverse=True)
    return render_template('equipment/detail.html', item=item, history=history)

@equipment_bp.route('/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_equipment(item_id):
    item = Equipment.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    # Equipment with movement history must not be deleted: doing so would erase
    # operation items and may delete operations that also reference other items.
    if OperationItem.query.filter_by(equipment_id=item.id).first():
        flash('Нельзя удалить оборудование с историей перемещений. Сначала разберите связанные операции.', 'danger')
        return redirect(url_for('equipment.detail', item_id=item.id))
    files = [p.filename for p in item.photos] + [item.photo_path, item.acceptance_report]
    op_ids = {oi.operation_id for oi in OperationItem.query.filter_by(equipment_id=item.id).all()}
    OperationItem.query.filter_by(equipment_id=item.id).delete()
    db.session.flush()
    for op_id in op_ids:
        if not OperationItem.query.filter_by(operation_id=op_id).first():
            Operation.query.filter_by(id=op_id).delete()
    name = item.name
    db.session.delete(item)
    db.session.commit()
    for f in files:
        if f:
            try: os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], f))
            except OSError: pass
    flash(f'Оборудование «{name}» удалено.', 'success')
    return redirect(url_for('equipment.list_equipment'))

@equipment_bp.route('/<int:item_id>/file/<kind>')
@login_required
def file(item_id, kind):
    item = Equipment.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    if kind == 'report':
        filename = item.acceptance_report
    elif kind == 'photo':
        requested = request.args.get('file')
        allowed = {p.filename for p in item.photos}
        if item.photo_path:
            allowed.add(item.photo_path)
        filename = requested if requested in allowed else item.photo_path
    else:
        filename = None
    if not filename:
        return ('Файл не найден', 404)
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename, as_attachment=(kind == 'report'))
