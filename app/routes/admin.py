import secrets, string
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, Project, Kit, Equipment, EquipmentPhoto, Employee, Operation, OperationItem

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.before_request
@login_required
def check_admin():
    if not current_user.is_admin:
        flash('Доступ только для администратора.', 'danger')
        return redirect(url_for('main.index'))

@admin_bp.route('/users', methods=['GET', 'POST'])
def manage_users():
    generated_password = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'user')
        if not password:
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for _ in range(10))
            generated_password = password
        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким именем уже существует!', 'danger')
        elif len(password) < 6:
            flash('Пароль должен содержать не менее 6 символов.', 'danger')
        else:
            user = User(username=username, role=role, must_change_password=True,
                        can_report=bool(request.form.get('can_report')), can_data=bool(request.form.get('can_data')))
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f'Учетная запись {username} создана. Пароль: {password}', 'success')
            return redirect(url_for('admin.manage_users'))
    users = User.query.all()
    return render_template('admin/users.html', users=users, generated_password=generated_password)

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('Учетную запись администратора удалить нельзя.', 'danger')
        return redirect(url_for('admin.manage_users'))

    # Удаляем связанные данные аккаунта в безопасном порядке, чтобы не
    # оставлять в базе осиротевшие записи и не нарушать внешние ключи.
    operations = Operation.query.filter_by(user_id=user.id).all()
    for operation in operations:
        OperationItem.query.filter_by(operation_id=operation.id).delete(synchronize_session=False)
    Operation.query.filter_by(user_id=user.id).delete(synchronize_session=False)

    equipments = Equipment.query.filter_by(user_id=user.id).all()
    equipment_ids = [eq.id for eq in equipments]
    if equipment_ids:
        EquipmentPhoto.query.filter(EquipmentPhoto.equipment_id.in_(equipment_ids)).delete(synchronize_session=False)
        OperationItem.query.filter(OperationItem.equipment_id.in_(equipment_ids)).delete(synchronize_session=False)
    Equipment.query.filter_by(user_id=user.id).delete(synchronize_session=False)

    Employee.query.filter_by(user_id=user.id).delete(synchronize_session=False)

    projects = Project.query.filter_by(user_id=user.id).all()
    project_ids = [project.id for project in projects]
    if project_ids:
        Kit.query.filter(Kit.project_id.in_(project_ids)).delete(synchronize_session=False)
    Project.query.filter_by(user_id=user.id).delete(synchronize_session=False)

    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f'Учетная запись {username} удалена.', 'success')
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/users/<int:user_id>/edit', methods=['POST'])
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if not username:
        flash('Логин не может быть пустым.', 'danger')
    elif User.query.filter(User.username == username, User.id != user.id).first():
        flash('Пользователь с таким логином уже существует!', 'danger')
    elif password and len(password) < 6:
        flash('Пароль должен содержать не менее 6 символов.', 'danger')
    else:
        user.username = username
        if password:
            user.set_password(password)
        user.can_report = bool(request.form.get('can_report'))
        user.can_data = bool(request.form.get('can_data'))
        db.session.commit()
        flash(f'Учетная запись {username} обновлена.', 'success')
    return redirect(url_for('admin.manage_users'))
