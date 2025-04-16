import sys
import os
from sqlalchemy import text
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask import Flask

# Ortam değişkenlerini yükle
load_dotenv()

# Flask uygulamasını oluştur
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
db = SQLAlchemy(app)

def run_update():
    with app.app_context():
        conn = db.engine.connect()
        
        try:
            # Önce sütunun var olup olmadığını kontrol et
            check_column = text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='roles' AND column_name='can_view_management';
            """)
            
            result = conn.execute(check_column)
            if result.rowcount == 0:
                # Sütun yok, ekle
                print("'can_view_management' sütunu ekleniyor...")
                add_column = text("""
                ALTER TABLE roles ADD COLUMN can_view_management BOOLEAN DEFAULT FALSE;
                """)
                conn.execute(add_column)
                conn.commit()
                print("Sütun başarıyla eklendi.")

                # Süper admin rollerinin can_view_management değerini true yap
                print("Süper admin rollerini güncelleniyor...")
                update_superadmin = text("""
                UPDATE roles SET can_view_management = TRUE WHERE is_superadmin = TRUE;
                """)
                conn.execute(update_superadmin)
                conn.commit()
                print("Süper admin rolleri güncellendi.")
                
                return True
            else:
                print("'can_view_management' sütunu zaten mevcut.")
                return False
                
        except Exception as e:
            conn.rollback()
            print(f"Hata oluştu: {e}")
            return False
        finally:
            conn.close()

if __name__ == "__main__":
    if run_update():
        print("Roller başarıyla güncellendi!")
    else:
        print("Roller güncellenemedi veya güncelleme gerekmedi.")