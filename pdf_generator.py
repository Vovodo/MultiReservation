#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import datetime
from weasyprint import HTML, CSS
from jinja2 import Environment, FileSystemLoader

def generate_monthly_report_pdf(branch_data, staff_data, month, year, branch_name):
    """
    Aylık rapor için PDF dosyası oluşturur
    
    Args:
        branch_data: Şube performans verileri
        staff_data: Personel performans verileri
        month: Ay (1-12)
        year: Yıl
        branch_name: Şube adı
    
    Returns:
        str: Oluşturulan PDF dosyasının yolu
    """
    # PDF dosyaları için klasör oluştur
    pdf_dir = os.path.join('static', 'reports')
    if not os.path.exists(pdf_dir):
        os.makedirs(pdf_dir)
    
    # Ay isimlerini Türkçe olarak belirle
    month_names = {
        1: 'Ocak', 2: 'Şubat', 3: 'Mart', 4: 'Nisan', 5: 'Mayıs', 6: 'Haziran',
        7: 'Temmuz', 8: 'Ağustos', 9: 'Eylül', 10: 'Ekim', 11: 'Kasım', 12: 'Aralık'
    }
    
    month_name = month_names.get(month, str(month))
    report_name = f"{branch_name}_{year}_{month}_{month_name}"
    pdf_path = os.path.join(pdf_dir, f"{report_name}.pdf")
    
    # Template dosyasını yükle
    env = Environment(loader=FileSystemLoader('templates'))
    template = env.get_template('report_pdf_template.html')
    
    # Template'e verileri gönder
    html_content = template.render(
        branch_name=branch_name,
        month_name=month_name,
        year=year,
        branch_data=branch_data,
        staff_data=staff_data,
        current_date=datetime.datetime.now().strftime('%d.%m.%Y')
    )
    
    # CSS ekle
    css = CSS(string='''
    @page {
        size: A4;
        margin: 1.5cm;
        @bottom-center {
            content: "Sayfa " counter(page) "/" counter(pages);
            font-size: 10px;
            color: #666;
        }
    }
    body {
        font-family: Arial, sans-serif;
        line-height: 1.5;
        color: #333;
    }
    .header {
        text-align: center;
        margin-bottom: 30px;
        padding-bottom: 20px;
        border-bottom: 2px solid #1a73e8;
    }
    .report-title {
        font-size: 28px;
        font-weight: bold;
        margin-bottom: 10px;
        color: #1a73e8;
    }
    .report-subtitle {
        font-size: 20px;
        margin-bottom: 10px;
        color: #444;
    }
    .section {
        margin-bottom: 30px;
        page-break-inside: avoid;
    }
    .section-title {
        font-size: 20px;
        font-weight: bold;
        margin-bottom: 15px;
        padding-bottom: 8px;
        border-bottom: 1px solid #ddd;
        color: #1a73e8;
    }
    .summary-box {
        display: flex;
        justify-content: space-between;
        margin-bottom: 25px;
        flex-wrap: wrap;
    }
    .summary-item {
        width: 30%;
        background-color: #f4f8ff;
        padding: 18px;
        border-radius: 8px;
        box-shadow: 0 3px 8px rgba(0,0,0,0.1);
        margin-bottom: 15px;
        border-left: 5px solid #1a73e8;
    }
    .summary-label {
        font-weight: bold;
        display: block;
        margin-bottom: 8px;
        color: #555;
        font-size: 14px;
    }
    .summary-value {
        font-size: 22px;
        font-weight: bold;
        color: #1a73e8;
    }
    .performance-metrics {
        display: flex;
        justify-content: space-between;
        margin-top: 20px;
        flex-wrap: wrap;
    }
    .metric-item {
        width: 30%;
        background-color: #f9f9f9;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 15px;
        text-align: center;
        border-top: 3px solid #34a853;
    }
    .metric-title {
        font-weight: bold;
        font-size: 14px;
        color: #555;
        margin-bottom: 8px;
    }
    .metric-value {
        font-size: 18px;
        color: #34a853;
        font-weight: bold;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 20px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
    th, td {
        border: 1px solid #ddd;
        padding: 12px;
        text-align: left;
    }
    th {
        background-color: #1a73e8;
        color: white;
        font-weight: bold;
    }
    tr:nth-child(even) {
        background-color: #f9f9f9;
    }
    .text-center {
        text-align: center;
    }
    .text-right {
        text-align: right;
    }
    .footer {
        margin-top: 40px;
        padding-top: 20px;
        border-top: 1px solid #ddd;
        text-align: center;
        color: #666;
        font-size: 12px;
    }
    ''')
    
    # HTML'i PDF'e dönüştür
    HTML(string=html_content).write_pdf(pdf_path, stylesheets=[css])
    
    return pdf_path

def archive_and_reset_monthly_data(branch_id=None):
    """
    Aylık verileri arşivler ve istatistikleri sıfırlar
    
    Args:
        branch_id: Belirli bir şube için arşivleme yapmak isterseniz şube ID'si (opsiyonel)
    
    Returns:
        bool: İşlemin başarılı olup olmadığı
    """
    from models import db, Branch, Log, Reservation
    from sqlalchemy import extract, func
    
    current_date = datetime.datetime.now()
    previous_month = current_date.month - 1 if current_date.month > 1 else 12
    previous_year = current_date.year if current_date.month > 1 else current_date.year - 1
    
    # Tüm şubeler için veya belirli bir şube için işlem yap
    branches_query = Branch.query
    if branch_id:
        branches_query = branches_query.filter_by(id=branch_id)
    
    branches = branches_query.all()
    archived_reports = []
    
    for branch in branches:
        # Önceki ay için rezervasyon verilerini topla
        reservations = Reservation.query.filter(
            Reservation.branch_id == branch.id,
            extract('month', Reservation.reservation_date) == previous_month,
            extract('year', Reservation.reservation_date) == previous_year,
            Reservation.is_canceled == False
        ).all()
        
        # Personel performans verilerini hesapla
        staff_data = []
        for staff in branch.staff:
            staff_reservations = [r for r in reservations if r.staff_id == staff.id]
            
            staff_data.append({
                'name': staff.name,
                'reservation_count': len(staff_reservations),
                'total_guests': sum(r.num_people for r in staff_reservations),
                'total_revenue': sum(r.total_price for r in staff_reservations)
            })
        
        # Şube toplam verilerini hesapla
        branch_data = {
            'reservation_count': len(reservations),
            'total_guests': sum(r.num_people for r in reservations),
            'total_revenue': sum(r.total_price for r in reservations)
        }
        
        # PDF raporu oluştur
        pdf_path = generate_monthly_report_pdf(
            branch_data=branch_data,
            staff_data=staff_data,
            month=previous_month,
            year=previous_year,
            branch_name=branch.name
        )
        
        # Arşivlenen rapor bilgisini kaydet
        archived_reports.append({
            'branch_name': branch.name,
            'pdf_path': pdf_path,
            'month': previous_month,
            'year': previous_year
        })
        
        # Log kaydı oluştur
        Log.add_log(
            log_type='SYSTEM',
            action='ARCHIVE',
            details=f"{previous_month}/{previous_year} dönemi için aylık rapor arşivlendi: {pdf_path}",
            branch_id=branch.id
        )
    
    return archived_reports

if __name__ == "__main__":
    # Test için
    print("PDF generator modülü yüklendi")