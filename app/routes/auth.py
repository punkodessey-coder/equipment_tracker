from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.extensions import db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('main.index'))
        flash('Неверный логин или пароль', 'danger')
    return render_template('auth/login.html')

@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old = request.form.get('old_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not current_user.check_password(old):
            flash('Текущий пароль указан неверно.', 'danger')
        elif len(new) < 6:
            flash('Новый пароль должен содержать не менее 6 символов.', 'danger')
        elif new != confirm:
            flash('Новые пароли не совпадают.', 'danger')
        else:
            current_user.set_password(new)
            current_user.must_change_password = False
            db.session.commit()
            flash('Пароль успешно изменён.', 'success')
            return redirect(url_for('main.index'))
    return render_template('auth/change_password.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы успешно вышли из системы', 'info')
    return redirect(url_for('auth.login'))
