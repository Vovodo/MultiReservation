#!/bin/bash
# Rezervasyon Sistemi VPS Kurulum Script
# Bu script, rezervasyon sistemini VPS'e otomatik olarak yükler ve yapılandırır

# Renkli çıktı için
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Root yetkisi kontrolü
if [ "$EUID" -ne 0 ]
  then echo -e "${RED}Bu script root yetkisi gerektirir. Lütfen 'sudo' ile çalıştırın.${NC}"
  exit
fi

# Kurulum dizini - script'in bulunduğu dizin
INSTALL_DIR=$(pwd)

# Kullanıcı adını al
echo -e "${YELLOW}VPS'de hangi kullanıcı ile işlem yapılacak? (Mevcut kullanıcı: $(whoami))${NC}"
read USERNAME

# Domain/IP adresini al
echo -e "${YELLOW}Sitenin çalışacağı domain adını veya IP adresini girin:${NC}"
read DOMAIN

# Gerekli paketleri yükle
echo -e "\n${GREEN}Gerekli paketler yükleniyor...${NC}"
apt update
apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx supervisor ufw

# Uygulama kullanıcısı kontrolü
if id "$USERNAME" &>/dev/null; then
    echo -e "${GREEN}$USERNAME kullanıcısı zaten mevcut.${NC}"
else
    echo -e "${GREEN}$USERNAME kullanıcısı oluşturuluyor...${NC}"
    adduser --disabled-password --gecos "" $USERNAME
    usermod -aG sudo $USERNAME
fi

# Uygulama dizini oluştur ve izinleri ayarla
echo -e "\n${GREEN}Uygulama dizinleri hazırlanıyor...${NC}"
mkdir -p /var/www/rezervasyon
mkdir -p /var/www/rezervasyon/logs
mkdir -p /var/www/rezervasyon/instance

# Mevcut dosyaları kopyala
echo -e "\n${GREEN}Uygulama dosyaları kopyalanıyor...${NC}"
cp -r $INSTALL_DIR/* /var/www/rezervasyon/
cp -r $INSTALL_DIR/.env /var/www/rezervasyon/ 2>/dev/null || echo -e "${YELLOW}.env dosyası bulunamadı, lütfen daha sonra manuel olarak ekleyin.${NC}"

# Dizin izinlerini ayarla
chown -R $USERNAME:$USERNAME /var/www/rezervasyon

# Virtual environment oluştur
echo -e "\n${GREEN}Python sanal ortamı oluşturuluyor...${NC}"
cd /var/www/rezervasyon
python3 -m venv venv
source venv/bin/activate

# Bağımlılıkları yükle
echo -e "\n${GREEN}Python bağımlılıkları yükleniyor...${NC}"
if [ -f "vps_requirements.txt" ]; then
    pip install -r vps_requirements.txt
else
    # Temel bağımlılıkları yükle
    pip install flask flask-login flask-sqlalchemy flask-wtf gunicorn psycopg2-binary python-dotenv python-telegram-bot weasyprint werkzeug wtforms email-validator apscheduler jinja2 pdfkit
fi

# Servis dosyası oluştur
echo -e "\n${GREEN}Systemd servis dosyası oluşturuluyor...${NC}"
cat > /etc/systemd/system/rezervasyon.service << EOF
[Unit]
Description=Rezervasyon Sistemi Flask Uygulaması
After=network.target

[Service]
User=$USERNAME
WorkingDirectory=/var/www/rezervasyon
Environment="PATH=/var/www/rezervasyon/venv/bin"
ExecStart=/var/www/rezervasyon/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 --access-logfile logs/access.log --error-logfile logs/error.log main:app

[Install]
WantedBy=multi-user.target
EOF

# Supervisor yapılandırması
echo -e "\n${GREEN}Supervisor yapılandırması oluşturuluyor...${NC}"
cat > /etc/supervisor/conf.d/rezervasyon.conf << EOF
[program:rezervasyon]
command=/var/www/rezervasyon/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 main:app
directory=/var/www/rezervasyon
user=$USERNAME
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stderr_logfile=/var/www/rezervasyon/logs/supervisor.err.log
stdout_logfile=/var/www/rezervasyon/logs/supervisor.out.log
EOF

# Nginx yapılandırması
echo -e "\n${GREEN}Nginx yapılandırması oluşturuluyor...${NC}"
cat > /etc/nginx/sites-available/rezervasyon << EOF
server {
    listen 80;
    server_name $DOMAIN;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Nginx yapılandırmasını etkinleştir
ln -sf /etc/nginx/sites-available/rezervasyon /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t || { echo -e "${RED}Nginx yapılandırması hatalı!${NC}"; exit 1; }

# Güvenlik duvarını yapılandır
echo -e "\n${GREEN}Güvenlik duvarı yapılandırılıyor...${NC}"
ufw allow 'Nginx Full'
ufw allow ssh
echo "y" | ufw enable

# Servisleri yeniden başlat
echo -e "\n${GREEN}Servisler başlatılıyor...${NC}"
systemctl daemon-reload
systemctl restart nginx
systemctl start rezervasyon
systemctl enable rezervasyon
supervisorctl reread
supervisorctl update
supervisorctl start rezervasyon

# SSL sertifikası kurulumu (isteğe bağlı)
echo -e "\n${YELLOW}SSL sertifikası kurmak ister misiniz? (evet/hayır)${NC}"
read SSL_INSTALL

if [[ "$SSL_INSTALL" == "evet" ]]; then
    echo -e "\n${GREEN}SSL sertifikası kuruluyor...${NC}"
    certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN
    systemctl restart nginx
fi

# Admin kullanıcısı oluştur
echo -e "\n${YELLOW}Admin kullanıcısı oluşturmak ister misiniz? (evet/hayır)${NC}"
read CREATE_ADMIN

if [[ "$CREATE_ADMIN" == "evet" ]]; then
    echo -e "\n${GREEN}Admin kullanıcısı oluşturuluyor...${NC}"
    cd /var/www/rezervasyon
    source venv/bin/activate
    python create_admin.py
fi

# Kurulum tamamlandı
echo -e "\n${GREEN}==========================================${NC}"
echo -e "${GREEN}Kurulum tamamlandı!${NC}"
echo -e "${GREEN}Sitenize şu adresten erişebilirsiniz: http://$DOMAIN${NC}"
echo -e "${GREEN}SSL kurulduysa: https://$DOMAIN${NC}"
echo -e "${GREEN}==========================================${NC}"
echo -e "\n${YELLOW}Önemli Notlar:${NC}"
echo -e "1. Admin kullanıcısı: admin / şifre: admin123 (güvenlik için değiştirin)"
echo -e "2. Log dosyaları: /var/www/rezervasyon/logs/"
echo -e "3. Servis yönetimi: 'systemctl start/stop/restart rezervasyon'"
echo -e "4. Nginx yönetimi: 'systemctl start/stop/restart nginx'"
echo -e "5. Sorun çıkarsa log dosyalarını kontrol edin: 'journalctl -u rezervasyon.service -f'"