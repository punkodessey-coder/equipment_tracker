import json, os, re, uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Equipment, Project, Employee, Operation, OperationItem, Kit
from datetime import datetime
from io import BytesIO

data_bp=Blueprint('data',__name__,url_prefix='/data')

@data_bp.before_request
@login_required
def check_data_access():
    if not current_user.can_use_data:
        flash('Экспорт/импорт базы данных недоступен для вашей учётной записи. Обратитесь к администратору.','danger')
        return redirect(url_for('main.index'))

def conflict_key(e):
    if not isinstance(e, dict):
        return None
    sn=(e.get('serial_number') or '').strip()
    dec=(e.get('decimal_number') or '').strip()
    return ('sn',sn.casefold()) if sn else ('dec',dec.casefold()) if dec else None


def validate_import_content(content):
    """Validate the complete JSON structure before creating any database rows."""
    if not isinstance(content, dict):
        raise ValueError('Корень JSON должен быть объектом.')
    collections = ('projects', 'kits', 'employees', 'equipments', 'operations')
    for key in collections:
        if key not in content:
            content[key] = []
        if not isinstance(content[key], list):
            raise ValueError(f'Поле «{key}» должно быть массивом.')
        if len(content[key]) > 50000:
            raise ValueError(f'В разделе «{key}» слишком много записей.')

    def valid_id(value):
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    def unique_records(key):
        seen = set()
        for index, record in enumerate(content[key]):
            if not isinstance(record, dict):
                raise ValueError(f'Запись {index + 1} в разделе «{key}» должна быть объектом.')
            rid = record.get('id')
            if not valid_id(rid):
                raise ValueError(f'У записи {index + 1} в разделе «{key}» отсутствует корректный id.')
            normalized = str(rid)
            if normalized in seen:
                raise ValueError(f'В разделе «{key}» повторяется id: {rid}.')
            seen.add(normalized)
        return seen

    project_ids = unique_records('projects')
    kit_ids = unique_records('kits')
    employee_ids = unique_records('employees')
    equipment_ids = unique_records('equipments')
    unique_records('operations')

    def required_text(record, key, label, max_length):
        value = record.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
            raise ValueError(f'Поле «{label}» должно быть непустой строкой длиной до {max_length} символов.')

    for p in content['projects']:
        required_text(p, 'name', 'название проекта', 120)
        if 'archived' in p and not isinstance(p['archived'], bool):
            raise ValueError('Поле archived проекта должно быть логическим значением.')

    for k in content['kits']:
        required_text(k, 'name', 'название комплекта', 120)
        if str(k.get('project_id')) not in project_ids:
            raise ValueError(f'Комплект «{k.get("name", "")}» ссылается на отсутствующий проект.')

    for e in content['employees']:
        required_text(e, 'full_name', 'ФИО сотрудника', 120)
        if e.get('kind') not in (None, '', 'own', 'other'):
            raise ValueError(f'Недопустимый тип сотрудника: {e.get("kind")!r}.')
        if e.get('department') is not None and (not isinstance(e['department'], str) or len(e['department']) > 120):
            raise ValueError('Некорректное поле department у сотрудника.')

    seen_identifiers = set()
    for e in content['equipments']:
        required_text(e, 'name', 'наименование оборудования', 120)
        for field, limit in (('serial_number', 100), ('decimal_number', 100), ('received_from', 255)):
            if e.get(field) is not None and (not isinstance(e[field], str) or len(e[field]) > limit):
                raise ValueError(f'Некорректное поле {field} у оборудования.')
        for field in ('serial_number', 'decimal_number'):
            value = (e.get(field) or '').strip()
            if value:
                ident = (field, value.casefold())
                if ident in seen_identifiers:
                    raise ValueError(f'В импортируемом файле повторяется {field}: {value}.')
                seen_identifiers.add(ident)
        status = e.get('status', 'На складе')
        if not isinstance(status, str) or len(status) > 80 or not (
            status == 'На складе' or status == 'Архивное' or
            (status.startswith('Выдано (') and status.endswith(')') and len(status) > 9)
        ):
            raise ValueError(f'Недопустимый статус оборудования: {status!r}.')
        pid, kid = e.get('project_id'), e.get('kit_id')
        if pid is not None and str(pid) not in project_ids:
            raise ValueError(f'Оборудование «{e["name"]}» ссылается на отсутствующий проект.')
        if kid is not None and str(kid) not in kit_ids:
            raise ValueError(f'Оборудование «{e["name"]}» ссылается на отсутствующий комплект.')
        if e.get('received_at') is not None:
            if not isinstance(e['received_at'], str):
                raise ValueError('received_at должен быть строкой даты ISO или null.')
            try:
                datetime.fromisoformat(e['received_at'])
            except ValueError as exc:
                raise ValueError(f'Некорректная дата received_at у оборудования «{e["name"]}».') from exc

    kits_by_id = {str(k['id']): str(k.get('project_id')) for k in content['kits']}
    for e in content['equipments']:
        kid, pid = e.get('kit_id'), e.get('project_id')
        if kid is not None and pid is not None and kits_by_id[str(kid)] != str(pid):
            raise ValueError(f'Комплект оборудования «{e["name"]}» относится к другому проекту.')

    for o in content['operations']:
        if o.get('op_type') not in ('issue', 'receive'):
            raise ValueError(f'Недопустимый тип операции: {o.get("op_type")!r}.')
        for field in ('employee_id', 'issuer_employee_id'):
            value = o.get(field)
            if value is not None and str(value) not in employee_ids:
                raise ValueError(f'Операция ссылается на отсутствующего сотрудника ({field}).')
        for field, limit in (('recipient_name', 255), ('comment', 10000)):
            value = o.get(field)
            if value is not None and (not isinstance(value, str) or len(value) > limit):
                raise ValueError(f'Некорректное поле {field} в операции.')
        if not isinstance(o.get('items', []), list):
            raise ValueError('Поле items операции должно быть массивом.')
        seen_items = set()
        for equipment_id in o.get('items', []):
            key = str(equipment_id)
            if key not in equipment_ids:
                raise ValueError(f'Операция ссылается на отсутствующее оборудование: {equipment_id}.')
            if key in seen_items:
                raise ValueError(f'В операции повторяется оборудование с id {equipment_id}.')
            seen_items.add(key)
        if o.get('created_at') is not None:
            if not isinstance(o['created_at'], str):
                raise ValueError('created_at операции должен быть строкой даты ISO или null.')
            try:
                datetime.fromisoformat(o['created_at'])
            except ValueError as exc:
                raise ValueError('Некорректная дата created_at в операции.') from exc

    return content


def _find_existing_equipment(user_id, key):
    if not key:
        return None
    field, normalized_value = key
    attr = 'serial_number' if field == 'sn' else 'decimal_number'
    for equipment in Equipment.query.filter_by(user_id=user_id).all():
        value = getattr(equipment, attr) or ''
        if value.strip().casefold() == normalized_value:
            return equipment
    return None

def do_import(content, choices=None):
    content = validate_import_content(content)
    choices = choices or {}
    allowed_choice_indexes = {str(i) for i, e in enumerate(content['equipments']) if _find_existing_equipment(current_user.id, conflict_key(e))}
    for index, decision in choices.items():
        if index not in allowed_choice_indexes or decision not in {'existing', 'incoming'}:
            raise ValueError('Недопустимый выбор при разрешении конфликтов импорта.')
    proj_map={}; emp_map={}; kit_map={}; eq_map={}
    for p in content.get('projects',[]):
        new=Project(user_id=current_user.id,name=p['name'],description=None,archived=p.get('archived',False)); db.session.add(new); db.session.flush(); proj_map[p['id']]=new.id
    for k in content.get('kits',[]):
        pid=proj_map.get(k.get('project_id'))
        if pid: new=Kit(project_id=pid,name=k['name']); db.session.add(new); db.session.flush(); kit_map[k['id']]=new.id
    for e in content.get('employees',[]):
        new=Employee(user_id=current_user.id,full_name=e['full_name'],kind=e.get('kind') or 'own',department=e.get('department')); db.session.add(new); db.session.flush(); emp_map[e['id']]=new.id
    for idx,e in enumerate(content.get('equipments',[])):
        existing=_find_existing_equipment(current_user.id, conflict_key(e))
        if existing:
            decision=choices.get(str(idx),'existing')
            if decision=='existing': eq_map[e['id']]=existing.id; continue
            if decision != 'incoming':
                raise ValueError('Недопустимый выбор при разрешении конфликтов импорта.')
        dt=datetime.fromisoformat(e['received_at']) if e.get('received_at') else datetime.utcnow()
        new=Equipment(user_id=current_user.id,name=e['name'],category=None,decimal_number=e.get('decimal_number'),serial_number=e.get('serial_number'),status=e.get('status','На складе'),project_id=proj_map.get(e.get('project_id')),kit_id=kit_map.get(e.get('kit_id')),received_at=dt,received_from=e.get('received_from')); db.session.add(new); db.session.flush(); eq_map[e['id']]=new.id
    top=db.session.query(db.func.max(Operation.seq_number)).filter(Operation.user_id==current_user.id).scalar() or 0
    for o in content.get('operations',[]):
        top+=1
        new=Operation(seq_number=top,user_id=current_user.id,op_type=o['op_type'],employee_id=emp_map.get(o.get('employee_id')),recipient_name=o.get('recipient_name'),issuer_employee_id=emp_map.get(o.get('issuer_employee_id')),comment=o.get('comment'),created_at=datetime.fromisoformat(o['created_at']) if o.get('created_at') else datetime.utcnow()); db.session.add(new); db.session.flush()
        for old_id in o.get('items',[]):
            if eq_map.get(old_id): db.session.add(OperationItem(operation_id=new.id,equipment_id=eq_map[old_id]))
    db.session.commit()

@data_bp.route('/')
@login_required
def index(): return render_template('data.html')

@data_bp.route('/export')
@login_required
def export_data():
    projects=Project.query.filter_by(user_id=current_user.id).all(); employees=Employee.query.filter_by(user_id=current_user.id).all(); equipments=Equipment.query.filter_by(user_id=current_user.id).all(); operations=Operation.query.filter_by(user_id=current_user.id).all(); kits=Kit.query.join(Project).filter(Project.user_id==current_user.id).all()
    data={'version':'3.1.1','exported_at':datetime.utcnow().isoformat(),'projects':[{'id':p.id,'name':p.name,'archived':p.archived} for p in projects],'kits':[{'id':k.id,'project_id':k.project_id,'name':k.name} for k in kits],'employees':[{'id':e.id,'full_name':e.full_name,'kind':e.kind or 'own','department':e.department} for e in employees],'equipments':[{'id':e.id,'name':e.name,'decimal_number':e.decimal_number,'serial_number':e.serial_number,'status':e.status,'project_id':e.project_id,'kit_id':e.kit_id,'received_at':e.received_at.isoformat() if e.received_at else None,'received_from':e.received_from} for e in equipments],'operations':[{'id':o.id,'op_type':o.op_type,'employee_id':o.employee_id,'recipient_name':o.recipient_name,'issuer_employee_id':o.issuer_employee_id,'comment':o.comment,'created_at':o.created_at.isoformat(),'items':[i.equipment_id for i in o.items]} for o in operations]}
    stream=BytesIO(json.dumps(data,ensure_ascii=False,indent=2).encode()); return send_file(stream,as_attachment=True,download_name=f'equipment_db_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json',mimetype='application/json')

@data_bp.route('/import',methods=['POST'])
@login_required
def import_data():
    file=request.files.get('file')
    if not file: flash('Выберите JSON файл для импорта.','danger'); return redirect(url_for('data.index'))
    try:
        content=validate_import_content(json.load(file)); conflicts=[]
        for idx,e in enumerate(content.get('equipments',[])):
            existing=_find_existing_equipment(current_user.id, conflict_key(e))
            if existing: conflicts.append({'idx':idx,'incoming':e,'existing':existing})
        if conflicts:
            token=uuid.uuid4().hex; path=os.path.join(current_app.config['UPLOAD_FOLDER'],f'.import_{current_user.id}_{token}.json')
            with open(path,'w',encoding='utf-8') as f: json.dump(content,f,ensure_ascii=False)
            return render_template('data_conflicts.html',conflicts=conflicts,token=token)
        do_import(content); flash('База данных успешно импортирована!','success')
    except Exception as err: db.session.rollback(); flash(f'Ошибка при импорте базы данных: {err}','danger')
    return redirect(url_for('data.index'))

@data_bp.route('/import/resolve',methods=['POST'])
@login_required
def resolve_import():
    token=request.form.get('token','')
    if not re.fullmatch(r'[0-9a-f]{32}',token):
        flash('Некорректный токен импорта.','danger'); return redirect(url_for('data.index'))
    path=os.path.join(current_app.config['UPLOAD_FOLDER'],f'.import_{current_user.id}_{token}.json')
    if not os.path.exists(path): flash('Файл импорта устарел или не найден.','danger'); return redirect(url_for('data.index'))
    try:
        with open(path,encoding='utf-8') as f: content=validate_import_content(json.load(f))
        choices={k.replace('choice_',''):v for k,v in request.form.items() if k.startswith('choice_')}
        do_import(content,choices); os.remove(path); flash('Импорт завершён с учётом выбранных конфликтов.','success')
    except Exception as err: db.session.rollback(); flash(f'Ошибка при импорте: {err}','danger')
    return redirect(url_for('data.index'))
