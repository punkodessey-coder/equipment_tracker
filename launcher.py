import os
import socket
import threading
import tkinter as tk
from tkinter import messagebox
from werkzeug.serving import make_server

from app import create_app, db, _ensure_schema
from app.models import User


def secret_file_path():
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser(r'~\\AppData\\Local')
        folder = os.path.join(base, 'Tracker')
    else:
        base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
        folder = os.path.join(base, 'Tracker')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, '.admin_password')


def initialize_database(app):
    _ensure_schema(app)
    with app.app_context():
        db.create_all()
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            import secrets
            password = secrets.token_urlsafe(9)
            admin = User(username='admin', role='admin', must_change_password=True)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            with open(secret_file_path(), 'w', encoding='utf-8') as f:
                f.write(password)
        elif not os.path.exists(secret_file_path()) and getattr(admin, 'password_plain', None):
            with open(secret_file_path(), 'w', encoding='utf-8') as f:
                f.write(admin.password_plain)


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


class Server:
    def __init__(self, app, host='0.0.0.0', port=5000):
        self.app = app
        self.host = host
        self.port = port
        self.httpd = None
        self.thread = None

    def start(self):
        self.httpd = make_server(self.host, self.port, self.app, threaded=True)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def restart(self, port):
        self.stop()
        self.port = port
        self.start()


def main():
    app = create_app()
    initialize_database(app)
    server = Server(app)
    server.start()

    root = tk.Tk()
    root.title('Трекер — управление сервером')
    root.geometry('440x230')
    root.resizable(False, False)

    tk.Label(root, text='Трекер', font=('Arial', 18, 'bold')).pack(pady=(16, 6))
    ip_var = tk.StringVar(value=local_ip())
    port_var = tk.StringVar(value=str(server.port))

    frame = tk.Frame(root)
    frame.pack(pady=6)
    tk.Label(frame, text='IP:').grid(row=0, column=0, sticky='e', padx=6, pady=4)
    tk.Label(frame, textvariable=ip_var, width=24, anchor='w').grid(row=0, column=1, sticky='w', padx=6)
    tk.Label(frame, text='Порт:').grid(row=1, column=0, sticky='e', padx=6, pady=4)
    tk.Entry(frame, textvariable=port_var, width=12).grid(row=1, column=1, sticky='w', padx=6)

    status = tk.StringVar(value=f'http://{ip_var.get()}:{server.port}')
    tk.Label(root, textvariable=status).pack(pady=4)

    def refresh():
        status.set(f'http://{ip_var.get()}:{server.port}')

    def apply_port():
        try:
            port = int(port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
            server.restart(port)
            refresh()
        except Exception as exc:
            messagebox.showerror('Ошибка', f'Не удалось запустить порт: {exc}')

    def open_browser():
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{server.port}')

    def close_all():
        try:
            server.stop()
        finally:
            root.destroy()

    buttons = tk.Frame(root)
    buttons.pack(pady=8)
    tk.Button(buttons, text='Применить порт', command=apply_port).pack(side='left', padx=4)
    tk.Button(buttons, text='Открыть Трекер', command=open_browser).pack(side='left', padx=4)
    tk.Button(buttons, text='Закрыть Трекер', command=close_all).pack(side='left', padx=4)

    root.protocol('WM_DELETE_WINDOW', close_all)
    root.mainloop()
    server.stop()


if __name__ == '__main__':
    main()
