#!/usr/bin/env python3
import sqlite3
import os
import datetime

print("Veritabanı şeması güncelleniyor...")

# Veritabanı bağlantısı oluştur
conn = sqlite3.connect('instance/reservation_system.db')
cur = conn.cursor()

# Reservations tablosunu güncelle
updates = [
    "ALTER TABLE reservations ADD COLUMN customer_id INTEGER",
    "ALTER TABLE reservations ADD COLUMN is_canceled BOOLEAN DEFAULT 0",
    "ALTER TABLE reservations ADD COLUMN cancel_type VARCHAR(20)",
    "ALTER TABLE reservations ADD COLUMN cancel_revenue FLOAT",
    "ALTER TABLE reservations ADD COLUMN updated_at DATETIME"
]

# Önce tüm güncellemeleri yap, sonra updated_at güncelle
try:
    # updated_at sütununa geçerli zamanı ekle
    cur.execute("UPDATE reservations SET updated_at = ?", (datetime.datetime.utcnow().isoformat(),))
    print("updated_at sütunu güncellendi")
except Exception as e:
    print(f"updated_at güncellenirken hata: {e}")

for update in updates:
    try:
        cur.execute(update)
        print(f"Güncelleme başarılı: {update}")
    except sqlite3.OperationalError as e:
        # Sütun zaten varsa hatayı görmezden gel
        if "duplicate column name" in str(e):
            print(f"Sütun zaten mevcut: {update}")
        else:
            print(f"Hata: {e} - {update}")

# Değişiklikleri kaydet
conn.commit()

# customers ve reservations tablolarını ilişkilendir
try:
    # Tüm rezervasyonları al
    cur.execute("SELECT id, customer_phone FROM reservations")
    reservations = cur.fetchall()
    
    for res_id, phone in reservations:
        # Her telefon için müşteri kimliğini bul
        cur.execute("SELECT id FROM customers WHERE phone = ?", (phone,))
        customer = cur.fetchone()
        
        # Eğer müşteri varsa, rezervasyonu güncelle
        if customer:
            customer_id = customer[0]
            cur.execute("UPDATE reservations SET customer_id = ? WHERE id = ?", (customer_id, res_id))
            print(f"Rezervasyon #{res_id} için müşteri ilişkisi güncellendi (Customer ID: {customer_id})")
    
    # Değişiklikleri kaydet
    conn.commit()
    print("Müşteri ilişkileri güncellendi")
    
except Exception as e:
    print(f"Müşteri ilişkileri güncellenirken hata: {e}")

# Bağlantıyı kapat
conn.close()

print("Veritabanı şeması güncelleme işlemi tamamlandı!")