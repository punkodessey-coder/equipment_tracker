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
    sn=(e.get('serial_number') or '').strip()
    dec=(e.get('decimal_number') or '').strip()
    return ('sn',sn.casefold()) if sn else ('dec',dec.casefold()) if dec else None

def do_import(content, choices=None):
    proj_map={}; emp_map={}; kit_map={}; eq_map={}
    for p in content.get('projects',[]):
        new=Project(user_id=current_user.id,name=p['name'],description=None,archived=p.get('archived',False)); db.session.add(new); db.session.flush(); proj_map[p['id']]=new.id
    for k in content.get('kits',[]):
        pid=proj_map.get(k.get('project_id'))
        if pid: new=Kit(project_id=pid,name=k['name']); db.session.add(new); db.session.flush(); kit_map[k['id']]=new.id
    for e in content.get('employees',[]):
        new=Employee(user_id=current_user.id,full_name=e['full_name'],kind=e.get('kind') or 'own',department=e.get('department')); db.session.add(new); db.session.flush(); emp_map[e['id']]=new.id
    choices=choices or {}
    for idx,e in enumerate(content.get('equipments',[])):
        key=conflict_key(e); existing=None
        if key:
            field,val=key
            existing=Equipment.query.filter_by(user_id=current_user.id,**{('serial_number' if field=='sn' else 'decimal_number'):val}).first()
        if existing:
            decision=choices.get(str(idx),'existing')
            if decision=='existing': eq_map[e['id']]=existing.id; continue
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
        content=json.load(file); conflicts=[]
        for idx,e in enumerate(content.get('equipments',[])):
            key=conflict_key(e); existing=None
            if key:
                field,val=key; existing=Equipment.query.filter_by(user_id=current_user.id,**{('serial_number' if field=='sn' else 'decimal_number'):val}).first()
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
        with open(path,encoding='utf-8') as f: content=json.load(f)
        choices={k:v for k,v in request.form.items() if k.startswith('choice_')}; choices={k.replace('choice_',''):v for k,v in choices.items()}
        do_import(content,choices); os.remove(path); flash('Импорт завершён с учётом выбранных конфликтов.','success')
    except Exception as err: db.session.rollback(); flash(f'Ошибка при импорте: {err}','danger')
    return redirect(url_for('data.index'))
