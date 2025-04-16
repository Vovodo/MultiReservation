import os
from sqlalchemy import text
from app import app, db

# Uygulama bağlamı oluştur
with app.app_context():
    # Veritabanını güncelle
    with db.engine.connect() as conn:
        try:
            # PostgreSQL için sütun ekleme işlemi
            # is_canceled sütununu ekle
            try:
                conn.execute(text("ALTER TABLE reservations ADD COLUMN is_canceled BOOLEAN DEFAULT FALSE;"))
                print("is_canceled sütunu eklendi.")
                conn.commit()
            except Exception as e:
                # Sütun zaten var hatasını yok say
                if "already exists" in str(e):
                    print("is_canceled sütunu zaten mevcut.")
                else:
                    raise e

            # cancel_type sütununu ekle
            try:
                conn.execute(text("ALTER TABLE reservations ADD COLUMN cancel_type VARCHAR(20);"))
                print("cancel_type sütunu eklendi.")
                conn.commit()
            except Exception as e:
                # Sütun zaten var hatasını yok say
                if "already exists" in str(e):
                    print("cancel_type sütunu zaten mevcut.")
                else:
                    raise e
                
        except Exception as e:
            print(f"Hata: {e}")