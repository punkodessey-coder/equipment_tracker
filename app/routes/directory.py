from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Project, Employee, Kit, Operation, Equipment
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

directory_bp = Blueprint('directory', __name__)

def owned_project(proj_id):
    return Project.query.filter_by(id=proj_id, user_id=current_user.id).first_or_404()

def unique_kit_names(names):
    clean=[]
    seen=set()
    duplicates=[]
    for name in names:
        name=name.strip()
        if not name:
            continue
        key=name.casefold()
        if key in seen:
            duplicates.append(name)
        else:
            clean.append(name); seen.add(key)
    return clean, duplicates

@directory_bp.route('/projects', methods=['GET', 'POST'])
@login_required
def projects():
    if request.method == 'POST':
        name=request.form.get('name','').strip()
        kit_names, duplicate_kits=unique_kit_names(request.form.getlist('kit_names'))
        if not name:
            flash('Укажите название проекта.','danger')
        elif duplicate_kits:
            flash('Нельзя создать два комплекта с одинаковым названием: ' + ', '.join(dict.fromkeys(duplicate_kits)), 'danger')
        elif Project.query.filter_by(user_id=current_user.id,name=name).first():
            flash('Проект с таким названием уже существует.','danger')
        else:
            proj=Project(user_id=current_user.id,name=name,description=None,archived=False)
            db.session.add(proj); db.session.flush()
            for n in kit_names: db.session.add(Kit(project_id=proj.id,name=n))
            db.session.commit(); flash('Проект успешно добавлен.','success')
            return redirect(url_for('directory.projects'))
    proj_list=Project.query.filter_by(user_id=current_user.id,archived=False).all()
    archived=Project.query.filter_by(user_id=current_user.id,archived=True).all()
    kit_counts={p.id:len(p.equipments) for p in proj_list+archived}
    return render_template('projects.html',projects=proj_list,archived_projects=archived,kit_counts=kit_counts)

@directory_bp.route('/projects/<int:proj_id>')
@login_required
def project_detail(proj_id):
    return render_template('project_detail.html',project=owned_project(proj_id))

@directory_bp.route('/projects/<int:proj_id>/edit',methods=['POST'])
@login_required
def edit_project(proj_id):
    proj=owned_project(proj_id)
    name=request.form.get('name','').strip()
    if not name:
        flash('Название проекта обязательно.','danger'); return redirect(url_for('directory.project_detail',proj_id=proj.id))
    other=Project.query.filter(Project.user_id==current_user.id,Project.name==name,Project.id!=proj.id).first()
    if other:
        flash('Проект с таким названием уже существует.','danger'); return redirect(url_for('directory.project_detail',proj_id=proj.id))
    proj.name=name
    db.session.commit(); flash('Проект обновлён.','success')
    return redirect(url_for('directory.project_detail',proj_id=proj.id))


@directory_bp.route('/projects/<int:proj_id>/kits/add',methods=['POST'])
@login_required
def add_kit(proj_id):
    proj=owned_project(proj_id); name=request.form.get('name','').strip()
    if not name or Kit.query.filter(Kit.project_id==proj.id,db.func.lower(Kit.name)==name.lower()).first():
        flash('Укажите уникальное название комплекта.','danger')
    else:
        db.session.add(Kit(project_id=proj.id,name=name)); db.session.commit(); flash('Комплект добавлен.','success')
    return redirect(url_for('directory.project_detail',proj_id=proj.id))
@directory_bp.route('/projects/<int:proj_id>/kit/<int:kit_id>/edit',methods=['POST'])
@login_required
def edit_kit(proj_id,kit_id):
    proj=owned_project(proj_id); kit=Kit.query.filter_by(id=kit_id,project_id=proj.id).first_or_404()
    name=request.form.get('name','').strip()
    duplicate=Kit.query.filter(Kit.project_id==proj.id,Kit.id!=kit.id,db.func.lower(Kit.name)==name.lower()).first()
    if not name or duplicate:
        flash('Название комплекта пустое или уже используется в этом проекте.','danger')
    else:
        kit.name=name; db.session.commit(); flash('Комплект обновлён.','success')
    return redirect(url_for('directory.project_detail',proj_id=proj.id))

@directory_bp.route('/projects/<int:proj_id>/delete',methods=['POST'])
@login_required
def delete_project(proj_id):
    proj=owned_project(proj_id)
    if request.form.get('confirm')!='DELETE':
        flash('Для удаления подтвердите действие повторно.','warning'); return redirect(url_for('directory.projects'))
    if proj.equipments:
        flash('Проект с оборудованием удалить нельзя. Сначала перенесите оборудование.','danger'); return redirect(url_for('directory.projects'))
    db.session.delete(proj); db.session.commit(); flash('Проект удалён.','success'); return redirect(url_for('directory.projects'))

@directory_bp.route('/projects/<int:proj_id>/kit/<int:kit_id>/delete',methods=['POST'])
@login_required
def delete_kit(proj_id,kit_id):
    proj=owned_project(proj_id); kit=Kit.query.filter_by(id=kit_id,project_id=proj.id).first_or_404()
    if request.form.get('confirm')!='DELETE':
        flash('Для удаления комплекта подтвердите действие повторно.','warning'); return redirect(url_for('directory.project_detail',proj_id=proj.id))
    if kit.equipments:
        flash('Комплект с оборудованием удалить нельзя.','danger'); return redirect(url_for('directory.project_detail',proj_id=proj.id))
    db.session.delete(kit); db.session.commit(); flash('Комплект удалён.','success'); return redirect(url_for('directory.project_detail',proj_id=proj.id))

@directory_bp.route('/projects/<int:proj_id>/archive',methods=['POST'])
@login_required
def archive_project(proj_id):
    proj=owned_project(proj_id)
    issued = [eq for eq in proj.equipments if (eq.status or '').startswith('Выдано (')]
    if issued:
        flash('Нельзя архивировать проект: сначала примите обратно выданное оборудование. Это сохранит корректный статус и историю перемещений.', 'danger')
        return redirect(url_for('directory.project_detail', proj_id=proj.id))
    try:
        proj.archived=True
        for eq in proj.equipments:
            if eq.status!='Архивное':
                eq.status_before_archive=eq.status
                eq.status='Архивное'
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Не удалось архивировать проект. Изменения отменены.', 'danger')
        return redirect(url_for('directory.project_detail', proj_id=proj.id))
    flash('Проект перенесён в архив.','success')
    return redirect(url_for('directory.projects'))

@directory_bp.route('/projects/<int:proj_id>/restore',methods=['POST'])
@login_required
def restore_project(proj_id):
    proj=owned_project(proj_id); proj.archived=False
    for eq in proj.equipments:
        if eq.status=='Архивное':
            eq.status=eq.status_before_archive or 'На складе'
            eq.status_before_archive=None
    db.session.commit(); flash('Проект возвращён из архива.','success'); return redirect(url_for('directory.projects'))

@directory_bp.route('/projects/<int:proj_id>/kit/<int:kit_id>')
@login_required
def kit_detail(proj_id,kit_id):
    project=owned_project(proj_id); kit=Kit.query.filter_by(id=kit_id,project_id=project.id).first_or_404()
    return render_template('kit_detail.html',kit=kit,project=project)

@directory_bp.route('/projects/<int:proj_id>/pdf')
@login_required
def project_pdf(proj_id):
    project=owned_project(proj_id); stream=BytesIO()
    font_path=os.path.abspath(os.path.join(os.path.dirname(__file__),'..','..','static','fonts','DejaVuSans.ttf'))
    pdfmetrics.registerFont(TTFont('DejaVu',font_path)); pdf=canvas.Canvas(stream,pagesize=A4); width,height=A4; y=height-45
    pdf.setFont('DejaVu',14); pdf.drawString(40,y,f'Состав проекта: {project.name}'); y-=28
    for kit in project.kits:
        if y<70: pdf.showPage(); y=height-45
        pdf.setFont('DejaVu',11); pdf.drawString(40,y,f'Комплект: {kit.name}'); y-=17; pdf.setFont('DejaVu',8)
        for eq in kit.equipments:
            if y<45: pdf.showPage(); y=height-45
            pdf.drawString(55,y,f'{eq.name} | Дец.: {eq.decimal_number or "—"} | S/N: {eq.serial_number or "—"}'[:125]); y-=13
        y-=8
    loose=[e for e in project.equipments if not e.kit_id]
    if loose:
        if y<70: pdf.showPage(); y=height-45
        pdf.setFont('DejaVu',11); pdf.drawString(40,y,'Без комплекта'); y-=17; pdf.setFont('DejaVu',8)
        for eq in loose:
            if y<45: pdf.showPage(); y=height-45
            pdf.drawString(55,y,f'{eq.name} | Дец.: {eq.decimal_number or "—"} | S/N: {eq.serial_number or "—"}'[:125]); y-=13
    pdf.save(); stream.seek(0)
    return send_file(stream,as_attachment=True,download_name=f'project_{project.id}_composition.pdf',mimetype='application/pdf')

@directory_bp.route('/employees',methods=['GET','POST'])
@login_required
def employees():
    if request.method=='POST':
        name=request.form.get('full_name','').strip()
        exists=any(e.full_name.strip().casefold()==name.casefold() for e in Employee.query.filter_by(user_id=current_user.id).all()) if name else True
        if name and not exists:
            db.session.add(Employee(user_id=current_user.id,full_name=name,kind='own')); db.session.commit(); flash('Сотрудник добавлен.','success')
        else: flash('Укажите уникальное ФИО сотрудника (такого ФИО ещё нет ни в одном списке).','danger')
        return redirect(url_for('directory.employees'))
    all_emps=Employee.query.filter_by(user_id=current_user.id).all()
    own=[e for e in all_emps if (e.kind or 'own')=='own']; other=[e for e in all_emps if e.kind=='other']
    return render_template('employees.html',employees=own,other_employees=other)

@directory_bp.route('/employees/<int:emp_id>/edit',methods=['POST'])
@login_required
def edit_employee(emp_id):
    emp=Employee.query.filter_by(id=emp_id,user_id=current_user.id).first_or_404(); name=request.form.get('full_name','').strip()
    if not name: flash('ФИО обязательно.','danger'); return redirect(url_for('directory.employees'))
    dup=any(e.id!=emp.id and e.full_name.strip().casefold()==name.casefold() for e in Employee.query.filter_by(user_id=current_user.id).all())
    if dup: flash('Сотрудник с таким ФИО уже есть в списке.','danger'); return redirect(url_for('directory.employees'))
    old=emp.full_name
    if emp.kind=='other':
        emp.department=request.form.get('department','').strip() or None
        if old!=name:
            # ФИО «внешнего» сотрудника хранится в операциях и статусах текстом - обновляем везде.
            for o in Operation.query.filter_by(user_id=current_user.id).all():
                if (o.recipient_name or '').strip().casefold()==old.strip().casefold(): o.recipient_name=name
            for eq in Equipment.query.filter_by(user_id=current_user.id).all():
                if eq.status==f'Выдано ({old})': eq.status=f'Выдано ({name})'
                if eq.received_from==old: eq.received_from=name
    emp.full_name=name; db.session.commit(); flash('Сотрудник обновлён.','success')
    return redirect(url_for('directory.employees'))

@directory_bp.route('/employees/<int:emp_id>/delete',methods=['POST'])
@login_required
def delete_employee(emp_id):
    emp=Employee.query.filter_by(id=emp_id,user_id=current_user.id).first_or_404()
    if request.form.get('confirm')!='DELETE': flash('Для удаления подтвердите действие повторно.','warning'); return redirect(url_for('directory.employees'))
    if emp.id in [o.employee_id for o in current_user.operations if o.employee_id] or emp.id in [o.issuer_employee_id for o in current_user.operations if o.issuer_employee_id]:
        flash('Сотрудник используется в истории операций и не может быть удалён.','danger')
    else: db.session.delete(emp); db.session.commit(); flash('Сотрудник удалён.','success')
    return redirect(url_for('directory.employees'))
