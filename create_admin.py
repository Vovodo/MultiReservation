#!/usr/bin/env python3
from app import app, db
from models import User, Role
from flask import Flask
from sqlalchemy import text

# Uygulama içeriğini başlat
with app.app_context():
    # Önce mevcut superadmin rolünü kontrol et
    superadmin_role = Role.query.filter_by(is_superadmin=True).first()
    
    if not superadmin_role:
        # Superadmin rolü oluştur
        superadmin_role = Role(
            name="Süper Admin",
            description="Tam yetkili yönetici",
            color="#ff0000",  # Kırmızı
            is_superadmin=True,
            can_create_reservation=True,
            can_view_reports=True,
            can_view_logs=True,
            can_view_settings=True,
            can_view_management=True
        )
        db.session.add(superadmin_role)
        db.session.commit()
        print("Süper Admin rolü oluşturuldu!")
    else:
        print("Süper Admin rolü zaten mevcut.")
    
    # Admin kullanıcısı oluştur
    admin_user = User.query.filter_by(username="admin").first()
    
    if not admin_user:
        # Admin kullanıcısını oluştur
        admin_user = User(
            username="admin",
            name="Administrator",
            email="admin@example.com",
            is_active=True
        )
        
        # Şifreyi ayarla
        admin_user.set_password("admin123")
        
        # Süper admin rolü ekle
        admin_user.roles.append(superadmin_role)
        
        db.session.add(admin_user)
        db.session.commit()
        
        print("Admin kullanıcısı oluşturuldu!")
        print("Kullanıcı adı: admin")
        print("Şifre: admin123")
    else:
        print("Admin kullanıcısı zaten mevcut.")