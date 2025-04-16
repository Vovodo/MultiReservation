#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, session
from app import app
from models import Branch

@app.route('/monthly-reports')
def monthly_reports():
    """Aylık raporlar sayfası - Arşivlenmiş PDF raporları listeler"""
    # reports klasörünü kontrol et, yoksa oluştur
    pdf_dir = os.path.join('static', 'reports')
    if not os.path.exists(pdf_dir):
        os.makedirs(pdf_dir)
    
    # PDF dosyalarını listele
    report_files = []
    for file in os.listdir(pdf_dir):
        if file.endswith('.pdf'):
            # Dosya adından bilgileri ayıkla (ŞubeAdı_YYYY_MM_AyAdı.pdf)
            try:
                file_parts = file.replace('.pdf', '').split('_')
                if len(file_parts) >= 4:
                    branch_name = file_parts[0]
                    year = file_parts[1]
                    month = file_parts[2]
                    month_name = file_parts[3]
                    
                    # Dosya istatistiklerini al
                    file_path = os.path.join(pdf_dir, file)
                    file_stats = os.stat(file_path)
                    created_date = datetime.fromtimestamp(file_stats.st_ctime)
                    
                    report_files.append({
                        'branch_name': branch_name,
                        'year': year,
                        'month': month,
                        'month_name': month_name,
                        'file_name': file,
                        'file_path': os.path.join('reports', file),
                        'created_date': created_date.strftime('%d.%m.%Y %H:%M')
                    })
            except Exception as e:
                # Dosya adı beklenen formatta değilse atla
                continue
    
    # Oluşturma tarihine göre azalan sırayla sırala (en yeniler üstte)
    report_files = sorted(report_files, key=lambda x: x['file_name'], reverse=True)
    
    # Şube listesini al
    branches = Branch.query.all()
    
    # Seçilen şube ID'sini session'dan al
    selected_branch_id = session.get('selected_branch_id')
    
    # Eğer seçili şube yoksa ve şubeler varsa, ilk şubeyi seç
    if not selected_branch_id and branches:
        selected_branch_id = branches[0].id
        session['selected_branch_id'] = int(selected_branch_id)
    
    return render_template(
        'monthly_reports.html',
        report_files=report_files,
        branches=branches,
        selected_branch_id=selected_branch_id
    )


@app.route('/generate-test-report')
def generate_test_report():
    """Test amaçlı olarak bir rapor oluştur"""
    branch_id = request.args.get('branch_id', type=int)
    
    # Yönetici yetkilendirmesi (gerçek uygulamada yetkisiz erişimi engellemek için)
    # Şu anda basitlik için atlandı
    
    try:
        from scheduler import generate_test_report
        reports = generate_test_report(branch_id)
        
        if reports and len(reports) > 0:
            # Başarı mesajı ve oluşturulan rapor bağlantısı
            flash(f'Rapor başarıyla oluşturuldu! {len(reports)} şube için rapor arşivlendi.', 'success')
            return redirect(url_for('monthly_reports'))
        else:
            flash('Rapor oluşturulamadı! Hiç veri bulunamadı veya bir hata oluştu.', 'warning')
    except Exception as e:
        flash(f'Rapor oluşturulurken hata: {str(e)}', 'danger')
    
    return redirect(url_for('monthly_reports'))