from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Equipment, Employee, Operation, OperationItem, Project, Kit
from docx import Document
from io import BytesIO

operations_bp = Blueprint('operations', __name__, url_prefix='/operations')

def find_employee(name_str):
    # Only people listed on the "Сотрудники" page may issue/accept equipment;
    # nobody is auto-created from these forms (compared in Python: SQLite lower() is ASCII-only).
    name_str = (name_str or '').strip().casefold()
    if not name_str:
        return None
    for emp in Employee.query.filter_by(user_id=current_user.id).all():
        if (emp.kind or 'own') == 'own' and emp.full_name.strip().casefold() == name_str:
            return emp
    return None

def ensure_other_employee(name):
    # Тот, кому выдали / от кого приняли, автоматически попадает в «Сотрудники других отделов»
    # (если такого ФИО ещё нет ни в одном списке).
    key = (name or '').strip().casefold()
    if not key:
        return
    for emp in Employee.query.filter_by(user_id=current_user.id).all():
        if emp.full_name.strip().casefold() == key:
            return
    db.session.add(Employee(user_id=current_user.id, full_name=name.strip(), kind='other'))

def next_seq():
    top = db.session.query(db.func.max(Operation.seq_number)).filter(Operation.user_id == current_user.id).scalar() or 0
    return top + 1

@operations_bp.route('/')
@login_required
def list_operations():
    # Отдельный журнал операций удалён из интерфейса: его функционал находится на Главной.
    return redirect(url_for('main.index'))

def operation_form(op_type='issue', op=None):
    all_emps=Employee.query.filter_by(user_id=current_user.id).order_by(Employee.full_name).all()
    employees=[e for e in all_emps if (e.kind or 'own')=='own']; other_employees=[e for e in all_emps if e.kind=='other']
    projects=Project.query.filter_by(user_id=current_user.id,archived=False).all()
    kits=Kit.query.join(Project).filter(Project.user_id==current_user.id,Project.archived==False).all()
    equipments=Equipment.query.filter_by(user_id=current_user.id).all()
    if op_type=='issue': equipments=[e for e in equipments if e.status.startswith('На складе')]
    selected_ids=[i.equipment_id for i in op.items] if op else []
    issued_to={e.id:e.status[len('Выдано ('):-1] for e in equipments if e.status.startswith('Выдано (') and e.status.endswith(')')}
    issued_names=sorted(set(issued_to.values()),key=str.casefold)
    return render_template('operations/new.html',equipments=equipments,employees=employees,projects=projects,kits=kits,selected_ids=selected_ids,issued_to=issued_to,issued_names=issued_names,other_employees=other_employees,op_type=op.op_type if op else op_type,op=op)

def _latest_operation_for(equipment_id, exclude_operation_id=None):
    query = (Operation.query.join(OperationItem, OperationItem.operation_id == Operation.id)
             .filter(Operation.user_id == current_user.id, OperationItem.equipment_id == equipment_id))
    if exclude_operation_id is not None:
        query = query.filter(Operation.id != exclude_operation_id)
    return query.order_by(Operation.created_at.desc(), Operation.id.desc()).first()


def _status_after_operation(operation):
    if not operation:
        return 'На складе'
    if operation.op_type == 'issue':
        return f'Выдано ({operation.party_name or "Не указано"})'
    return 'На складе'


def _has_later_operation(operation, equipment_ids):
    if not equipment_ids:
        return False
    items = OperationItem.query.filter(OperationItem.equipment_id.in_(equipment_ids)).all()
    for item in items:
        other = Operation.query.filter_by(id=item.operation_id, user_id=current_user.id).first()
        if other and other.id != operation.id and (other.created_at, other.id) > (operation.created_at, operation.id):
            return True
    return False


@operations_bp.route('/new', methods=['GET','POST'])
@login_required
def new_operation():
    op_type=request.args.get('type','issue')
    if request.method=='POST':
        op_type=request.form.get('op_type','issue')
        if op_type not in {'issue', 'receive'}:
            flash('Недопустимый тип операции.', 'danger')
            return redirect(url_for('operations.new_operation'))
        employee_name=(request.form.get('employee_name') or '').strip()
        issuer_name=(request.form.get('issuer_name') or '').strip()
        raw_ids=request.form.getlist('equipment_ids')
        equipment_ids=list(dict.fromkeys(raw_ids))
        comment=(request.form.get('comment') or '').strip() or None
        if not equipment_ids:
            flash('Выберите хотя бы одну позицию из списка оборудования.','warning')
            return redirect(url_for('operations.new_operation',type=op_type))
        if len(equipment_ids) != len(raw_ids):
            flash('В списке оборудования есть повторяющиеся позиции. Операция не сохранена.', 'danger')
            return redirect(url_for('operations.new_operation',type=op_type))
        issuer=find_employee(issuer_name)
        if not issuer:
            flash('Укажите сотрудника из списка «Сотрудники», который оформляет операцию.', 'danger')
            return redirect(url_for('operations.new_operation',type=op_type))
        if not employee_name:
            flash('Укажите вторую сторону операции.', 'danger')
            return redirect(url_for('operations.new_operation',type=op_type))
        equipments = Equipment.query.filter(
            Equipment.user_id == current_user.id, Equipment.id.in_(equipment_ids)
        ).all()
        by_id = {str(eq.id): eq for eq in equipments}
        if len(by_id) != len(equipment_ids):
            flash('Одна или несколько позиций не найдены или недоступны. Операция не сохранена.', 'danger')
            return redirect(url_for('operations.new_operation',type=op_type))
        for eq in equipments:
            if eq.project and eq.project.archived:
                flash(f'Оборудование «{eq.name}» находится в архивном проекте.', 'danger')
                return redirect(url_for('operations.new_operation',type=op_type))
            allowed = eq.status.startswith('На складе') if op_type == 'issue' else eq.status.startswith('Выдано (')
            if not allowed:
                flash(f'Нельзя выполнить операцию для «{eq.name}»: текущий статус «{eq.status}». Ничего не сохранено.', 'danger')
                return redirect(url_for('operations.new_operation',type=op_type))
        try:
            ensure_other_employee(employee_name)
            operation=Operation(user_id=current_user.id,seq_number=next_seq(),op_type=op_type,
                employee_id=None,recipient_name=employee_name,issuer_employee_id=issuer.id,comment=comment)
            db.session.add(operation)
            db.session.flush()
            for eq in equipments:
                db.session.add(OperationItem(operation_id=operation.id,equipment_id=eq.id))
                eq.status=f'Выдано ({employee_name})' if op_type=='issue' else 'На складе'
                if op_type=='receive':
                    eq.received_from=employee_name
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to create equipment operation')
            flash('Не удалось сохранить операцию. Изменения отменены.', 'danger')
            return redirect(url_for('operations.new_operation',type=op_type))
        flash('Выдача успешно сохранена.' if op_type=='issue' else 'Приём успешно сохранён.','success')
        return redirect(url_for('main.index'))
    if op_type not in {'issue', 'receive'}:
        op_type = 'issue'
    return operation_form(op_type)


@operations_bp.route('/edit/<int:op_id>', methods=['GET', 'POST'])
@login_required
def edit_operation(op_id):
    op = Operation.query.filter_by(id=op_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        new_type = (request.form.get('op_type') or '').strip()
        recipient = (request.form.get('employee_name') or '').strip()
        issuer = find_employee(request.form.get('issuer_name'))
        raw_ids = request.form.getlist('equipment_ids')
        equipment_ids = list(dict.fromkeys(raw_ids))
        if new_type not in {'issue', 'receive'}:
            flash('Недопустимый тип операции.', 'danger')
            return redirect(url_for('operations.edit_operation', op_id=op.id))
        if not issuer or not recipient:
            flash('Укажите сотрудника из списка «Сотрудники» и вторую сторону операции.', 'danger')
            return redirect(url_for('operations.edit_operation', op_id=op.id))
        if not equipment_ids:
            flash('Выберите хотя бы одну позицию из списка оборудования.', 'warning')
            return redirect(url_for('operations.edit_operation', op_id=op.id))
        if len(equipment_ids) != len(raw_ids):
            flash('В списке оборудования есть повторяющиеся позиции. Изменения не сохранены.', 'danger')
            return redirect(url_for('operations.edit_operation', op_id=op.id))

        old_ids = {item.equipment_id for item in op.items}
        equipments = Equipment.query.filter(
            Equipment.user_id == current_user.id, Equipment.id.in_(equipment_ids)
        ).all()
        by_id = {str(eq.id): eq for eq in equipments}
        if len(by_id) != len(equipment_ids):
            flash('Одна или несколько позиций не найдены или недоступны. Изменения не сохранены.', 'danger')
            return redirect(url_for('operations.edit_operation', op_id=op.id))
        affected_ids = old_ids | {eq.id for eq in equipments}
        if _has_later_operation(op, affected_ids):
            flash('Нельзя редактировать историческую операцию: по одному из этих объектов уже есть более поздняя операция. Сначала исправьте последующие операции.', 'danger')
            return redirect(url_for('operations.edit_operation', op_id=op.id))

        prior_status = {}
        for eq_id in old_ids:
            previous = _latest_operation_for(eq_id, exclude_operation_id=op.id)
            if previous and (previous.created_at, previous.id) < (op.created_at, op.id):
                prior_status[eq_id] = _status_after_operation(previous)
            elif op.op_type == 'issue':
                prior_status[eq_id] = 'На складе'
            elif new_type == op.op_type and old_ids == {int(value) for value in equipment_ids}:
                # Metadata-only edits do not require reconstructing an unknown pre-history status.
                prior_status[eq_id] = 'На складе'
            else:
                flash('Нельзя безопасно изменить состав или тип первой операции приёма: предыдущий статус этой позиции неизвестен.', 'danger')
                return redirect(url_for('operations.edit_operation', op_id=op.id))

        for eq in equipments:
            status = prior_status.get(eq.id, eq.status)
            if eq.project and eq.project.archived:
                flash(f'Оборудование «{eq.name}» находится в архивном проекте. Изменения не сохранены.', 'danger')
                return redirect(url_for('operations.edit_operation', op_id=op.id))
            metadata_only = new_type == op.op_type and old_ids == {int(value) for value in equipment_ids}
            allowed = metadata_only or (status.startswith('На складе') if new_type == 'issue' else status.startswith('Выдано ('))
            if not allowed:
                flash(f'Нельзя изменить операцию для «{eq.name}»: перед этой операцией статус был «{status}». Изменения не сохранены.', 'danger')
                return redirect(url_for('operations.edit_operation', op_id=op.id))

        try:
            ensure_other_employee(recipient)
            # Use the ORM relationship so delete-orphan and the in-memory collection stay in sync.
            op.items.clear()
            db.session.flush()
            op.op_type = new_type
            op.employee_id = None
            op.recipient_name = recipient
            op.issuer_employee_id = issuer.id
            op.comment = (request.form.get('comment') or '').strip() or None
            for eq in equipments:
                db.session.add(OperationItem(operation_id=op.id,equipment_id=eq.id))
            db.session.flush()
            for eq_id in affected_ids:
                eq = Equipment.query.filter_by(id=eq_id, user_id=current_user.id).first()
                if not eq:
                    continue
                latest = _latest_operation_for(eq_id)
                if latest:
                    eq.status = _status_after_operation(latest)
                elif eq_id in old_ids:
                    eq.status = prior_status[eq_id]
                else:
                    eq.status = 'На складе'
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to edit equipment operation')
            flash('Не удалось обновить операцию. Все изменения отменены.', 'danger')
            return redirect(url_for('operations.edit_operation', op_id=op.id))
        flash('Операция успешно обновлена!', 'success')
        return redirect(url_for('operations.detail', op_id=op.id))
    return operation_form(op.op_type, op)


@operations_bp.route('/delete/<int:op_id>', methods=['POST'])
@login_required
def delete_operation(op_id):
    op = Operation.query.filter_by(id=op_id, user_id=current_user.id).first_or_404()
    eq_ids = {item.equipment_id for item in op.items}
    if _has_later_operation(op, eq_ids):
        flash('Нельзя удалить историческую операцию: по одному из этих объектов уже есть более поздняя операция. Сначала исправьте последующие операции.', 'danger')
        return redirect(url_for('main.index'))
    if op.op_type == 'receive':
        for eq_id in eq_ids:
            previous = _latest_operation_for(eq_id, exclude_operation_id=op.id)
            if not previous or (previous.created_at, previous.id) > (op.created_at, op.id):
                flash('Нельзя удалить первую операцию приёма: исходный статус оборудования неизвестен, поэтому его нельзя восстановить безопасно.', 'danger')
                return redirect(url_for('main.index'))
    try:
        # Operation.items has delete-orphan cascade; let SQLAlchemy delete the children once.
        db.session.delete(op)
        db.session.flush()
        for eq_id in eq_ids:
            eq = Equipment.query.filter_by(id=eq_id, user_id=current_user.id).first()
            if eq:
                eq.status = _status_after_operation(_latest_operation_for(eq_id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to delete equipment operation')
        flash('Не удалось удалить операцию. Изменения отменены.', 'danger')
        return redirect(url_for('main.index'))
    flash('Операция удалена.', 'success')
    return redirect(url_for('main.index'))

@operations_bp.route('/<int:op_id>')
@login_required
def detail(op_id):
    op = Operation.query.filter_by(id=op_id, user_id=current_user.id).first_or_404()
    return render_template('operations/detail.html', op=op)

@operations_bp.route('/doc/<int:op_id>')
@login_required
def generate_docx(op_id):
    op = Operation.query.filter_by(id=op_id, user_id=current_user.id).first_or_404()
    doc = Document()
    doc.add_heading('АКТ ПРИЕМА-ПЕРЕДАЧИ ОБОРУДОВАНИЯ', level=1)
    doc.add_paragraph(f'Операция № {op.seq_number or op.id}')
    date_str = op.created_at.strftime('%d.%m.%Y г.')
    type_str = 'выдано' if op.op_type == 'issue' else 'принято'
    party_a = op.issuer.full_name if op.issuer else 'Представитель компании'
    party_b = op.party_full or '—'
    doc.add_paragraph(f'Дата оформления: {date_str}')
    doc.add_paragraph(f'Настоящим подтверждается, что {date_str} оборудование было {type_str}.')
    doc.add_paragraph(f"{'Кто выдал' if op.op_type == 'issue' else 'Кто принял'}: {party_a}")
    doc.add_paragraph(f"{'Кому выдано' if op.op_type == 'issue' else 'От кого принято'}: {party_b}")
    if op.comment: doc.add_paragraph(f'Основание: {op.comment}')
    table = doc.add_table(rows=1, cols=5); table.style = 'Table Grid'
    for c, text in zip(table.rows[0].cells, ['№','Наименование','Децимальный номер','Серийный номер','Проект / комплект']):
        c.text = text
    for idx, item in enumerate(op.items, 1):
        eq=item.equipment; row=table.add_row().cells
        row[0].text=str(idx); row[1].text=eq.name; row[2].text=eq.decimal_number or '—'; row[3].text=eq.serial_number or '—'
        row[4].text=f'{eq.project.name if eq.project else "—"} / {eq.kit.name if eq.kit else "—"}'
    f_stream=BytesIO(); doc.save(f_stream); f_stream.seek(0)
    return send_file(f_stream, as_attachment=True, download_name=f'akt_peredachi_op_{op.id}.docx',
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
