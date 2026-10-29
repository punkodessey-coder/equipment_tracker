from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
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

@operations_bp.route('/new', methods=['GET','POST'])
@login_required
def new_operation():
    op_type=request.args.get('type','issue')
    if request.method=='POST':
        op_type=request.form.get('op_type','issue')
        employee_name=request.form.get('employee_name','').strip()
        issuer_name=request.form.get('issuer_name','').strip()
        equipment_ids=request.form.getlist('equipment_ids')
        comment=request.form.get('comment','').strip() or None
        if not equipment_ids: flash('Выберите хотя бы одну позицию из списка оборудования.','warning'); return redirect(url_for('operations.new_operation',type=op_type))
        issuer=find_employee(issuer_name)
        if not issuer:
            flash('Укажите, кто выдал, выбрав сотрудника из списка (страница «Сотрудники»).' if op_type=='issue' else 'Укажите, кто принял, выбрав сотрудника из списка (страница «Сотрудники»).','danger'); return redirect(url_for('operations.new_operation',type=op_type))
        if not employee_name:
            flash('Укажите, кому выдано оборудование.' if op_type=='issue' else 'Укажите, от кого принято оборудование.','danger'); return redirect(url_for('operations.new_operation',type=op_type))
        ensure_other_employee(employee_name)
        operation=Operation(user_id=current_user.id,seq_number=next_seq(),op_type=op_type,employee_id=None,recipient_name=employee_name,issuer_employee_id=issuer.id,comment=comment)
        db.session.add(operation); db.session.flush()
        for eq_id in equipment_ids:
            eq=Equipment.query.filter_by(id=eq_id,user_id=current_user.id).first()
            if not eq: continue
            if op_type=='issue' and not eq.status.startswith('На складе'): continue
            if op_type=='receive' and not eq.status.startswith('Выдано'): continue
            db.session.add(OperationItem(operation_id=operation.id,equipment_id=eq.id))
            eq.status=f'Выдано ({employee_name})' if op_type=='issue' else 'На складе'
            if op_type=='receive': eq.received_from=employee_name
        db.session.commit(); flash('Выдача успешно сохранена.' if op_type=='issue' else 'Прием успешно сохранен.','success')
        return redirect(url_for('main.index'))
    return operation_form(op_type)

@operations_bp.route('/edit/<int:op_id>', methods=['GET', 'POST'])
@login_required
def edit_operation(op_id):
    op = Operation.query.filter_by(id=op_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        op.op_type = request.form.get('op_type', op.op_type)
        recipient = (request.form.get('employee_name') or '').strip()
        issuer = find_employee(request.form.get('issuer_name'))
        equipment_ids = request.form.getlist('equipment_ids')
        if not issuer or not recipient:
            flash('Укажите сотрудника из списка «Сотрудники» (кто выдал / кто принял) и вторую сторону операции.', 'danger')
            return redirect(url_for('operations.edit_operation', op_id=op.id))
        if not equipment_ids:
            flash('Выберите хотя бы одну позицию из списка оборудования.', 'warning')
            return redirect(url_for('operations.edit_operation', op_id=op.id))
        ensure_other_employee(recipient)
        op.employee_id = None
        op.recipient_name = recipient
        op.issuer_employee_id = issuer.id
        op.comment = request.form.get('comment', '').strip() or None
        OperationItem.query.filter_by(operation_id=op.id).delete()
        for eq_id in equipment_ids:
            eq = Equipment.query.filter_by(id=eq_id, user_id=current_user.id).first()
            if eq:
                db.session.add(OperationItem(operation_id=op.id, equipment_id=eq.id))
                eq.status = f'Выдано ({recipient})' if op.op_type == 'issue' else 'На складе'
        db.session.commit()
        flash('Операция успешно обновлена!', 'success')
        return redirect(url_for('operations.detail', op_id=op.id))
    return operation_form(op.op_type, op)

@operations_bp.route('/delete/<int:op_id>', methods=['POST'])
@login_required
def delete_operation(op_id):
    op = Operation.query.filter_by(id=op_id, user_id=current_user.id).first_or_404()
    eq_ids = [i.equipment_id for i in OperationItem.query.filter_by(operation_id=op.id).all()]
    latest_for = {}
    for eq_id in eq_ids:
        last = (Operation.query.join(OperationItem, OperationItem.operation_id == Operation.id)
                .filter(OperationItem.equipment_id == eq_id).order_by(Operation.created_at.desc(), Operation.id.desc()).first())
        latest_for[eq_id] = last.id == op.id
    OperationItem.query.filter_by(operation_id=op.id).delete()
    db.session.delete(op)
    db.session.flush()
    for eq_id, was_latest in latest_for.items():
        if not was_latest: continue
        eq = Equipment.query.filter_by(id=eq_id, user_id=current_user.id).first()
        if not eq: continue
        prev = (Operation.query.join(OperationItem, OperationItem.operation_id == Operation.id)
                .filter(OperationItem.equipment_id == eq_id).order_by(Operation.created_at.desc(), Operation.id.desc()).first())
        eq.status = f'Выдано ({prev.party_name})' if prev and prev.op_type == 'issue' else 'На складе'
    db.session.commit()
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
