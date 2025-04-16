#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
# from apscheduler.triggers.cron import CronTrigger
from pdf_generator import archive_and_reset_monthly_data

# Loglama için dosya oluştur
if not os.path.exists('logs'):
    os.makedirs('logs')
logging.basicConfig(
    filename='logs/scheduler.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('scheduler')

def initialize_scheduler():
    """
    Zamanlanmış görevleri başlatan scheduler'ı oluşturur
    """
    try:
        # Basit bir scheduler oluştur
        scheduler = BackgroundScheduler()
        
        # Test için şimdilik başlatma işlemi yeterli, cron zamanlaması ayrıca yapılacak
        logger.info("Scheduler başlatıldı")
        scheduler.start()
        return scheduler
    except Exception as e:
        logger.error(f"Scheduler başlatılırken hata: {str(e)}")
        return None

def monthly_report_job():
    """
    Her ayın başında çalışacak görev
    - Önceki ayın raporlarını PDF olarak arşivler
    """
    try:
        logger.info("Aylık rapor arşivleme işlemi başlatılıyor...")
        reports = archive_and_reset_monthly_data()
        
        for report in reports:
            logger.info(f"Rapor arşivlendi: {report['branch_name']} - {report['month']}/{report['year']} - {report['pdf_path']}")
        
        logger.info(f"Aylık rapor arşivleme tamamlandı. Toplam {len(reports)} rapor oluşturuldu.")
        return True
    except Exception as e:
        logger.error(f"Aylık rapor arşivleme sırasında hata: {str(e)}", exc_info=True)
        return False

def generate_test_report(branch_id=None):
    """
    Test amaçlı olarak hemen bir rapor oluşturur
    """
    try:
        reports = archive_and_reset_monthly_data(branch_id)
        logger.info(f"Test raporu oluşturuldu: {len(reports)} rapor")
        return reports
    except Exception as e:
        logger.error(f"Test raporu oluşturma sırasında hata: {str(e)}", exc_info=True)
        return None