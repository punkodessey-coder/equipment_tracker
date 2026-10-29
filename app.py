import os
import secrets
from app import create_app, db
from app.models import User

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            password = secrets.token_urlsafe(9)
            admin = User(username='admin', role='admin', must_change_password=True)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            print('=' * 60)
            print('Создана учетная запись администратора: admin')
            print(f'Пароль: {password}')
            print('Пароль также виден администратору на странице "Учетные записи".')
            print('При первом входе будет предложено сменить пароль.')
            print('=' * 60)

    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', debug=debug_mode, port=int(os.environ.get('PORT', 5000)))
