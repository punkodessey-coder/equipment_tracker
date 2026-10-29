import socket
from io import BytesIO
from flask import Blueprint, render_template, request, Response, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import Operation, Equipment, OperationItem, Project
main_bp = Blueprint('main', __name__)

def _lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1)); return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()

def connect_url():
    # Адрес, по которому другие устройства подключаются к Трекеру (IP и порт сервера).
    host = request.host
    name, _, port = host.partition(':') if not host.startswith('[') else (host, '', '')
    if name in ('localhost', '127.0.0.1', '0.0.0.0', ''):
        host = _lan_ip() + (':' + port if port else '')
    return f'{request.scheme}://{host}'

@main_bp.route('/qr.svg')
def qr_svg():
    try:
        import segno
        buf = BytesIO(); segno.make(connect_url(), error='m').save(buf, kind='svg', scale=6, border=1, dark='#000000', light='#ffffff')
        return Response(buf.getvalue(), mimetype='image/svg+xml')
    except Exception:
        return Response('', status=404)
@main_bp.route('/')
@login_required
def index():
    from datetime import datetime, timedelta
    f_type=request.args.get('type',''); f_proj=request.args.get('project',type=int); f_from=request.args.get('date_from',''); f_to=request.args.get('date_to',''); f_q=request.args.get('q','').strip()
    q = Operation.query.filter_by(user_id=current_user.id)
    if f_type in ('issue','receive'): q = q.filter(Operation.op_type==f_type)
    if f_proj:
        q = q.filter(Operation.items.any(OperationItem.equipment.has(Equipment.project_id==f_proj)))
    try:
        if f_from: q = q.filter(Operation.created_at>=datetime.strptime(f_from,'%Y-%m-%d'))
        if f_to: q = q.filter(Operation.created_at<datetime.strptime(f_to,'%Y-%m-%d')+timedelta(days=1))
    except ValueError:
        pass
    filtered = bool(f_type in ('issue','receive') or f_proj or f_from or f_to or f_q)
    q = q.order_by(Operation.created_at.desc())
    recent_ops = q.all()
    for o in recent_ops:
        o.project_names = sorted({i.equipment.project.name for i in o.items if i.equipment and i.equipment.project})
    if f_q:
        needle = f_q.lower()
        def matches(o):
            parts = [o.issuer.full_name if o.issuer else '', o.party_name or '', o.comment or '', ' '.join(o.project_names),
                     'выдача' if o.op_type == 'issue' else 'прием', o.created_at.strftime('%d.%m.%Y %H:%M')]
            return needle in ' '.join(parts).lower()
        recent_ops = [o for o in recent_ops if matches(o)]
    projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.name).all()
    return render_template('index.html', recent_ops=recent_ops, projects=projects, f_type=f_type, f_proj=f_proj, f_from=f_from, f_to=f_to, f_q=f_q, filtered=filtered)
@main_bp.route('/stock')
@login_required
def stock():
    items = Equipment.query.filter_by(user_id=current_user.id, status='На складе').all()
    return render_template('stock.html', items=items)
@main_bp.route('/help')
@login_required
def help_page():
    return render_template('help.html', version='3.1.4')

@main_bp.route('/report')
@login_required
def report_page():
    if not current_user.can_use_report:
        flash('Формирование отчёта недоступно для вашей учётной записи. Обратитесь к администратору.','danger'); return redirect(url_for('main.index'))
    return render_template('report.html')

@main_bp.route('/report/generate')
@login_required
def generate_report():
    from flask import send_file
    from datetime import datetime, timedelta
    if not current_user.can_use_report:
        flash('Формирование отчёта недоступно для вашей учётной записи. Обратитесь к администратору.','danger'); return redirect(url_for('main.index'))
    start_s=request.args.get('start'); end_s=request.args.get('end'); fmt=request.args.get('format','pdf')
    try:
        start=datetime.strptime(start_s,'%Y-%m-%d'); end=datetime.strptime(end_s,'%Y-%m-%d')+timedelta(days=1)
    except Exception:
        flash('Укажите корректный период.','danger'); return redirect(url_for('main.report_page'))
    if end-start>timedelta(days=62):
        flash('Период отчёта не должен превышать двух месяцев.','danger'); return redirect(url_for('main.report_page'))
    ops=Operation.query.filter(Operation.user_id==current_user.id,Operation.created_at>=start,Operation.created_at<end).order_by(Operation.created_at).all()
    rows=[]
    for o in ops:
        for item in o.items:
            eq=item.equipment
            rows.append([o.created_at.strftime('%d.%m.%Y %H:%M'),'Выдача' if o.op_type=='issue' else 'Приём',o.issuer.full_name if o.issuer else '—',o.party_name or '—',eq.name,eq.decimal_number or '—',eq.serial_number or '—',eq.project.name if eq.project else '—',eq.kit.name if eq.kit else '—',eq.status])
    if fmt=='xlsx':
        from openpyxl import Workbook
        stream=BytesIO(); wb=Workbook(); ws=wb.active; ws.title='Отчёт'; ws.append(['Дата','Операция','Кто выдал / Кто принял','Кому выдано / От кого принято','Оборудование','Децимальный номер','Серийный номер','Проект','Комплект','Статус'])
        for r in rows: ws.append(r)
        wb.save(stream); stream.seek(0); return send_file(stream,as_attachment=True,download_name='tracker_report.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os
    stream=BytesIO(); font=os.path.abspath(os.path.join(os.path.dirname(__file__),'..','..','static','fonts','DejaVuSans.ttf')); pdfmetrics.registerFont(TTFont('DejaVu',font)); pdf=canvas.Canvas(stream,pagesize=landscape(A4)); w,h=landscape(A4); y=h-30; pdf.setFont('DejaVu',11); pdf.drawString(25,y,f'Отчёт за {start.strftime("%d.%m.%Y")} — {(end-timedelta(days=1)).strftime("%d.%m.%Y")}'); y-=22; pdf.setFont('DejaVu',6)
    headers=['Дата','Операция','Кто выдал / Кто принял','Кому выдано / От кого принято','Оборудование','Дец.','S/N','Проект','Комплект','Статус']; widths=[55,48,95,105,100,65,70,75,65,65]; x0=20
    for i,hdr in enumerate(headers): pdf.drawString(x0+sum(widths[:i]),y,hdr)
    y-=12
    for row in rows:
        if y<25: pdf.showPage(); y=h-30; pdf.setFont('DejaVu',6)
        for i,val in enumerate(row): pdf.drawString(x0+sum(widths[:i]),y,str(val)[:18])
        y-=10
    pdf.save(); stream.seek(0); return send_file(stream,as_attachment=True,download_name='tracker_report.pdf',mimetype='application/pdf')
