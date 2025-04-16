import os
import logging
import re
from datetime import datetime
# Telegram modüllerini düzgün bir şekilde import ediyoruz
try:
    # python-telegram-bot 20.x için
    from telegram import Bot, Update
    from telegram.constants import ParseMode
    from telegram.ext import CommandHandler, MessageHandler, filters, Application, CallbackContext
    # İsteğe bağlı modüller - gerekli oldukça kullancağız
    HAS_TELEGRAM = True
except ImportError:
    # Telegram modülleri bulunamadı, sahte sınıflar oluştur
    class Bot:
        def __init__(self, token):
            self.token = token
        
        def send_message(self, chat_id, text, parse_mode=None):
            logging.info(f"[DEVRE DIŞI] Telegram mesajı gönderilecekti: {chat_id}")
            return True

    class ParseMode:
        HTML = "HTML"
        MARKDOWN = "MARKDOWN"

    class Update:
        pass

    class CommandHandler:
        def __init__(self, cmd, func):
            pass

    class Updater:
        def __init__(self, token, use_context=True):
            self.token = token
        
        def start_polling(self):
            pass
        
        def idle(self):
            pass
        
        def stop(self):
            pass
        
        @property
        def dispatcher(self):
            return self

        def add_handler(self, handler):
            pass

    class CallbackContext:
        pass
    
    class Filters:
        command = None
    
    class MessageHandler:
        def __init__(self, filters, callback):
            pass
            
    HAS_TELEGRAM = False
    
from flask import current_app, g
import threading

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global updater object and bot state
bot_updater = None
bot_lock = threading.Lock()
update_id_offset = 0  # Son işlenen Update ID'sini takip etmek için

def bot_is_running():
    """
    Check if the bot is currently running
    
    Returns:
        bool: True if the bot is running, False otherwise
    """
    global bot_updater
    with bot_lock:
        return bot_updater is not None

def get_bot_token():
    """
    Get bot token from environment variables or database
    """
    # First try environment variable
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    # If not in environment variables, try to get from database
    if not token:
        try:
            from models import Setting
            
            # Veritabanından token'ı almaya çalış
            token = Setting.get('telegram_bot_token')
            if token:
                logger.info("Telegram bot token loaded from database")
        except Exception as e:
            logger.error(f"Error getting token from database: {e}")
    
    if token:
        # Token'ın ilk ve son birkaç karakterini logla, ama tamamını değil
        if len(token) > 10:
            masked_token = f"{token[:6]}...{token[-4:]}"
            logger.info(f"Using Telegram bot token: {masked_token}")
        else:
            logger.info("Telegram bot token found")
    else:
        logger.warning("No Telegram bot token found in environment variables or database")
    
    return token

def send_message(chat_id, message):
    """
    Send a message to a specific Telegram chat/group/channel
    
    Args:
        chat_id (str): The chat ID to send the message to
        message (str): The message text to send
    """
    try:
        # Directly send message in the current thread (which is already a background thread)
        # This is simpler and avoids nested threading issues
        token = get_bot_token()
        if not token:
            logger.error("Telegram Bot Token is not set")
            return False
        
        # Log details for debugging
        logger.info(f"Attempting to send message using token: {token[:5]}...{token[-4:]} to chat_id: {chat_id}")
        
        # Convert chat_id to int if it's a string containing numbers
        if isinstance(chat_id, str) and chat_id.lstrip('-').isdigit():
            chat_id = int(chat_id)
            logger.info(f"Converting chat_id to integer: {chat_id}")
        
        # Create bot and send message
        import asyncio
        
        async def send_async_message():
            bot = Bot(token=token)
            await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
            logger.info(f"Message successfully sent to chat {chat_id}")
            return True
            
        # python-telegram-bot 20.x sürümünde async kullanımı gerekli
        return asyncio.run(send_async_message())
            
    except Exception as e:
        logger.error(f"Error sending message to Telegram: {e}")
        # Print detailed error for debugging
        import traceback
        logger.error(f"Detailed error: {traceback.format_exc()}")
        return False

def send_reservation_notification(reservation, branch, staff):
    """
    Send reservation notification to the branch's Telegram channel
    
    Args:
        reservation: The reservation object
        branch: The branch object
        staff: The staff object
    """
    # Add a debug log to track number of calls
    logger.info(f"send_reservation_notification called for reservation ID: {reservation.id}")
    
    if not branch.telegram_enabled or not branch.telegram_chat_id:
        logger.info(f"Telegram notifications disabled for branch {branch.name}")
        return
    
    try:    
        # Calculate advance payment
        advance_payment = 0
        try:
            # If advance_payment_amount is a method
            if callable(getattr(reservation, 'advance_payment_amount', None)):
                advance_payment = reservation.advance_payment_amount()
            # If it's a direct attribute
            elif hasattr(reservation, 'advance_payment_amount'):
                advance_payment = reservation.advance_payment_amount
            # Otherwise calculate manually
            else:
                advance_payment = (reservation.advance_payment_percentage / 100) * reservation.total_price
        except Exception as e:
            logger.error(f"Error calculating advance payment: {e}")
            advance_payment = 0
            
        # Calculate remaining amount
        remaining_amount = reservation.total_price - advance_payment
        
        # Format reservation date/time
        formatted_date = reservation.reservation_date.strftime('%d.%m.%Y')
        formatted_time = reservation.reservation_time.strftime('%H:%M')
        
        # Ödeme tipini Türkçeleştir
        payment_type_tr = {
            "CASH": "🧾 Nakit",
            "POS": "💳 Kredi Kartı",
            "IBAN": "🏦 Havale/EFT",
            "OTHER": "📝 Diğer"
        }.get(reservation.payment_type, reservation.payment_type)
        
        # Ödeme durumunu emojilerle belirt
        payment_status = {
            "PENDING": "⏳ Ödeme Bekliyor",
            "ADVANCE": "💰 Ön Ödeme Yapıldı",
            "PAID": "✅ Tamamen Ödendi"
        }.get(reservation.payment_status, reservation.payment_status)
        
        # Create message
        message = f"""
<b>🎉 YENİ REZERVASYON OLUŞTURULDU 🎉</b>
━━━━━━━━━━━━━━━━━━━━━━━

🏢 <b>Şube:</b> {branch.name}
👤 <b>Müşteri:</b> {reservation.customer_name}
📞 <b>Telefon:</b> {reservation.customer_phone}
👥 <b>Kişi Sayısı:</b> {reservation.num_people}
🗓️ <b>Tarih/Saat:</b> {formatted_date} | ⏰ {formatted_time}
👨‍💼 <b>Personel:</b> {staff.name}

💵 <b>Toplam Ücret:</b> ₺{reservation.total_price:.2f}
💸 <b>Ön Ödeme:</b> ₺{advance_payment:.2f} (%{reservation.advance_payment_percentage})
💱 <b>Kalan Tutar:</b> ₺{remaining_amount:.2f}
💳 <b>Ödeme Tipi:</b> {payment_type_tr}
📊 <b>Ödeme Durumu:</b> {payment_status}

🆔 <b>Rezervasyon ID:</b> #{reservation.id}
━━━━━━━━━━━━━━━━━━━━━━━
<i>Bu mesaj otomatik olarak gönderilmiştir.</i>
"""
        
        # Send message
        logger.info(f"Attempting to send notification for reservation ID: {reservation.id}")
        send_message(branch.telegram_chat_id, message)
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        # Print detailed error for debugging
        import traceback
        logger.error(f"Detailed error: {traceback.format_exc()}")

def send_cancellation_notification(reservation, branch, staff, with_refund=False, operator_name=None):
    """
    Send reservation cancellation notification to the branch's Telegram channel
    
    Args:
        reservation: The reservation object
        branch: The branch object
        staff: The staff object
        with_refund: Whether this is a full refund cancellation
        operator_name: Name of person who cancelled (optional)
    """
    # Add a debug log to track number of calls
    logger.info(f"send_cancellation_notification called for reservation ID: {reservation.id}")
    
    if not branch.telegram_enabled or not branch.telegram_chat_id:
        logger.info(f"Telegram notifications disabled for branch {branch.name}")
        return False
    
    try:    
        # Format reservation date/time
        formatted_date = reservation.reservation_date.strftime('%d.%m.%Y')
        formatted_time = reservation.reservation_time.strftime('%H:%M')
        
        # Calculate advance payment
        advance_payment = 0
        try:
            # If advance_payment_amount is a method
            if callable(getattr(reservation, 'advance_payment_amount', None)):
                advance_payment = reservation.advance_payment_amount()
            # If it's a direct attribute
            elif hasattr(reservation, 'advance_payment_amount'):
                advance_payment = reservation.advance_payment_amount
            # Otherwise calculate manually
            else:
                advance_payment = (reservation.advance_payment_percentage / 100) * reservation.total_price
        except Exception as e:
            logger.error(f"Error calculating advance payment: {e}")
            advance_payment = 0
        
        # İptal tipine göre ikonu belirleme
        if with_refund:
            cancel_title = "💰 REZERVASYON TAM İADE İLE İPTAL EDİLDİ"
            cancel_emoji = "🔙"  # Geri ödeme olduğunu belirten emoji
        else:
            cancel_title = "❌ REZERVASYON İPTAL EDİLDİ"
            cancel_emoji = "💸"  # Para kalıyor emojisi
        
        # Ödeme bilgisi
        refund_info = ""
        if with_refund:
            refund_info = f"\n💱 <b>İade Edilen Tutar:</b> ₺{advance_payment:.2f} (Tam İade)"
        else:
            refund_info = f"\n💸 <b>Kesinti Yapılan Tutar:</b> ₺{advance_payment:.2f} (%{reservation.advance_payment_percentage})" if advance_payment > 0 else ""
        
        # İptal eden bilgisi
        operator_info = f"\n👨‍💼 <b>İptal Eden:</b> {operator_name}" if operator_name else ""
        
        # Mesaj oluşturma
        message = f"""
<b>{cancel_title}</b>
━━━━━━━━━━━━━━━━━━━━━━━

🏢 <b>Şube:</b> {branch.name}
👤 <b>Müşteri:</b> {reservation.customer_name}
📞 <b>Telefon:</b> {reservation.customer_phone}
👥 <b>Kişi Sayısı:</b> {reservation.num_people}
🗓️ <b>Tarih/Saat:</b> {formatted_date} | ⏰ {formatted_time}
👨‍💼 <b>Personel:</b> {staff.name}

💵 <b>Toplam Ücret:</b> ₺{reservation.total_price:.2f}{refund_info}
🆔 <b>Rezervasyon ID:</b> #{reservation.id}{operator_info}

{cancel_emoji} <i>Bu rezervasyon {"<b>tam iade ile</b>" if with_refund else ""} iptal edilmiştir. İlgili randevu saati artık boşta.</i>
━━━━━━━━━━━━━━━━━━━━━━━
<i>Bu mesaj otomatik olarak gönderilmiştir.</i>
"""
        
        # Send message
        logger.info(f"Attempting to send cancellation notification for reservation ID: {reservation.id}")
        result = send_message(branch.telegram_chat_id, message)
        return result
    except Exception as e:
        logger.error(f"Error sending cancellation notification: {e}")
        # Print detailed error for debugging
        import traceback
        logger.error(f"Detailed error: {traceback.format_exc()}")
        return False
        
def handle_iptal_command(update, context):
    """
    Handle /iptal [id] command - Cancel reservation but keep advance payment in revenue
    """
    try:
        logger.info(f"Received /iptal command in chat {update.effective_chat.id}")
        
        # Get reservation ID from command argument
        if not context.args or not context.args[0].isdigit():
            update.message.reply_text("Lütfen geçerli bir rezervasyon ID'si girin. Örnek: /iptal 123")
            return
            
        reservation_id = int(context.args[0])
        
        # Get operator info (the person who issued the command)
        operator_name = update.effective_user.full_name or update.effective_user.username or "Bilinmeyen Kullanıcı"
        from_chat_id = update.effective_chat.id
        
        # Execute cancellation in a thread to avoid blocking bot
        thread = threading.Thread(
            target=process_cancellation,
            args=(reservation_id, from_chat_id, operator_name, False),
            daemon=True
        )
        thread.start()
        
    except Exception as e:
        logger.error(f"Error in iptal command: {e}")
        update.message.reply_text(f"Hata oluştu: {str(e)}")

def handle_iade_command(update, context):
    """
    Handle /iade [id] command - Cancel reservation with full refund
    """
    try:
        logger.info(f"Received /iade command in chat {update.effective_chat.id}")
        
        # Get reservation ID from command argument
        if not context.args or not context.args[0].isdigit():
            update.message.reply_text("Lütfen geçerli bir rezervasyon ID'si girin. Örnek: /iade 123")
            return
            
        reservation_id = int(context.args[0])
        
        # Get operator info (the person who issued the command)
        operator_name = update.effective_user.full_name or update.effective_user.username or "Bilinmeyen Kullanıcı"
        from_chat_id = update.effective_chat.id
        
        # Execute cancellation in a thread to avoid blocking bot
        thread = threading.Thread(
            target=process_cancellation,
            args=(reservation_id, from_chat_id, operator_name, True),
            daemon=True
        )
        thread.start()
        
    except Exception as e:
        logger.error(f"Error in iade command: {e}")
        update.message.reply_text(f"Hata oluştu: {str(e)}")

def handle_rez_command(update, context):
    """
    Handle /rez command - List all upcoming reservations sorted by date and time
    """
    try:
        logger.info(f"Received /rez command in chat {update.effective_chat.id}")
        chat_id = update.effective_chat.id
        
        # Import models and app within the function to avoid circular imports
        from models import db, Reservation, Branch
        from app import app
        from datetime import datetime, date
        from sqlalchemy import and_, or_
        
        # Use application context
        with app.app_context():
            # Get branch for this chat
            branch = Branch.query.filter_by(telegram_chat_id=str(chat_id)).first()
            
            if not branch:
                update.message.reply_text("❌ Bu Telegram grubu herhangi bir şube ile ilişkilendirilmemiş.")
                return
            
            # Get upcoming reservations for this branch
            today = date.today()
            now = datetime.now()
            
            # Select both today's future reservations and all upcoming days
            # İptal edilmeyen rezervasyonları filtrele - bu çok önemli!
            reservations = Reservation.query.filter(
                and_(
                    Reservation.branch_id == branch.id,
                    Reservation.is_canceled == False,  # İptal edilmemiş rezervasyonları filtrele
                    or_(
                        # Today but after current time
                        and_(
                            Reservation.reservation_date == today,
                            Reservation.reservation_time >= now.time()
                        ),
                        # Future days
                        Reservation.reservation_date > today
                    )
                )
            ).order_by(
                Reservation.reservation_date, 
                Reservation.reservation_time
            ).all()
            
            if not reservations:
                update.message.reply_text("📅 Önümüzdeki günlerde hiç rezervasyon bulunmuyor.")
                return
                
            # Format reservations list
            message_lines = [f"📋 <b>{branch.name} - Yaklaşan Rezervasyonlar</b>"]
            message_lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
            
            current_date = None
            for r in reservations:
                # Add date header when date changes
                if current_date != r.reservation_date:
                    current_date = r.reservation_date
                    date_str = r.reservation_date.strftime('%d.%m.%Y')
                    message_lines.append(f"\n🗓️ <b>{date_str}</b>")
                
                # Format time
                time_str = r.reservation_time.strftime('%H:%M')
                
                # Ödeme durumuna göre emoji
                payment_emoji = {
                    "PENDING": "⏳",
                    "ADVANCE": "💰",
                    "PAID": "✅"
                }.get(r.payment_status, "❓")
                
                # Kişi sayısına göre emoji
                people_emoji = "👤" if r.num_people == 1 else "👥"
                
                # Add reservation details
                message_lines.append(
                    f"⏰ <b>{time_str}</b> | {payment_emoji} | {people_emoji} {r.num_people} | {r.customer_name} | 📞 {r.customer_phone} | 🆔 <code>{r.id}</code>"
                )
            
            # Join all lines and send message
            message_lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
            message_lines.append("<i>📝 Detaylar için: /detay [id]</i>")
            message_lines.append("<i>❌ İptal için: /iptal [id] veya /iade [id]</i>")
            message = "\n".join(message_lines)
            update.message.reply_html(message)
            
    except Exception as e:
        logger.error(f"Error in rez command: {e}")
        import traceback
        logger.error(f"Detailed error: {traceback.format_exc()}")
        update.message.reply_text(f"Hata oluştu: {str(e)}")

def handle_detay_command(update, context):
    """
    Handle /detay [id] command - Show detailed information for a specific reservation
    """
    try:
        logger.info(f"Received /detay command in chat {update.effective_chat.id}")
        chat_id = update.effective_chat.id
        
        # Get reservation ID from command args
        if not context.args or not context.args[0].isdigit():
            update.message.reply_text("❌ Kullanım: /detay [rezervasyon_id]")
            return
            
        reservation_id = int(context.args[0])
        
        # Import models and app within the function to avoid circular imports
        from models import db, Reservation, Branch, Staff
        from app import app
        
        # Use application context
        with app.app_context():
            # Get branch for this chat
            branch = Branch.query.filter_by(telegram_chat_id=str(chat_id)).first()
            
            if not branch:
                update.message.reply_text("❌ Bu Telegram grubu herhangi bir şube ile ilişkilendirilmemiş.")
                return
            
            # Get reservation by ID (only for this branch)
            # İptal edilmiş olsa bile rezervasyonu göster - detay komutunda bu önemli
            reservation = Reservation.query.filter(
                Reservation.id == reservation_id,
                Reservation.branch_id == branch.id
            ).first()
            
            if not reservation:
                update.message.reply_text(f"❌ Rezervasyon bulunamadı: #{reservation_id}")
                return
                
            # Get staff info
            staff = Staff.query.get(reservation.staff_id)
            staff_name = staff.name if staff else "Bilinmeyen Personel"
            
            # Calculate advance payment
            advance_payment = reservation.advance_payment_amount
            remaining_amount = reservation.total_price - advance_payment
            
            # Format date and time
            date_str = reservation.reservation_date.strftime('%d.%m.%Y')
            time_str = reservation.reservation_time.strftime('%H:%M')
            
            # Get payment status text
            payment_status_text = {
                "PENDING": "⏳ Ödeme Bekliyor",
                "ADVANCE": "💰 Ön Ödeme Yapıldı",
                "PAID": "✅ Tamamen Ödendi"
            }.get(reservation.payment_status, reservation.payment_status)
            
            # Get payment type text
            payment_type_text = {
                "CASH": "Nakit",
                "POS": "Kredi Kartı",
                "IBAN": "Havale/EFT",
                "OTHER": "Diğer"
            }.get(reservation.payment_type, reservation.payment_type)
            
            # Ödeme tipini Türkçeleştir ve emoji ekle
            payment_type_text = {
                "CASH": "🧾 Nakit",
                "POS": "💳 Kredi Kartı",
                "IBAN": "🏦 Havale/EFT",
                "OTHER": "📝 Diğer"
            }.get(reservation.payment_type, reservation.payment_type)
            
            # Check if reservation is canceled
            cancel_status = ""
            cancel_header = ""
            if reservation.is_canceled:
                if reservation.cancel_type == "REFUND":
                    cancel_status = "⚠️ <b>Bu rezervasyon TAM İADE ile iptal edilmiştir.</b>\n"
                    cancel_header = "🔙 İPTAL EDİLMİŞ REZERVASYON (TAM İADE) 🔙"
                else:
                    cancel_status = "⚠️ <b>Bu rezervasyon iptal edilmiştir (ön ödeme iade edilmedi).</b>\n"
                    cancel_header = "❌ İPTAL EDİLMİŞ REZERVASYON ❌"
            else:
                cancel_header = "🎫 REZERVASYON DETAYLARI 🎫"
            
            # Create detailed message
            message = f"""
<b>{cancel_header}</b>
━━━━━━━━━━━━━━━━━━━━━━━

🆔 <b>Rezervasyon ID:</b> #{reservation.id}
{cancel_status}
👤 <b>Müşteri:</b> {reservation.customer_name}
📞 <b>Telefon:</b> {reservation.customer_phone}
🗓️ <b>Tarih:</b> {date_str} 
⏰ <b>Saat:</b> {time_str}
👥 <b>Kişi Sayısı:</b> {reservation.num_people}

💵 <b>Toplam Tutar:</b> ₺{reservation.total_price:.2f}
💰 <b>Ödeme Durumu:</b> {payment_status_text}
💳 <b>Ödeme Tipi:</b> {payment_type_text}

💸 <b>Avans Ödeme:</b> %{reservation.advance_payment_percentage} (₺{advance_payment:.2f})
💱 <b>Kalan Tutar:</b> ₺{remaining_amount:.2f}

🏢 <b>Şube:</b> {branch.name}
👨‍💼 <b>Personel:</b> {staff_name}
⏱ <b>Oluşturma:</b> {reservation.created_at.strftime('%d.%m.%Y %H:%M')}
━━━━━━━━━━━━━━━━━━━━━━━
            """
            
            # Send the detailed information
            update.message.reply_html(message)
            
    except Exception as e:
        logger.error(f"Error in detay command: {e}")
        import traceback
        logger.error(f"Detailed error: {traceback.format_exc()}")
        update.message.reply_text(f"Hata oluştu: {str(e)}")
        
def process_cancellation(reservation_id, chat_id, operator_name, with_refund):
    """
    Process reservation cancellation based on ID
    """
    try:
        logger.info(f"Processing cancellation for reservation ID {reservation_id} by {operator_name}, with_refund={with_refund}")
        
        # Import models and app within the function to avoid circular imports
        from models import db, Reservation, Branch, Staff, Log
        from flask import current_app
        from app import app
        
        # Use application context
        with app.app_context():
            # Find reservation
            reservation = Reservation.query.get(reservation_id)
            if not reservation:
                logger.error(f"Reservation with ID {reservation_id} not found")
                send_message(chat_id, f"❌ Rezervasyon bulunamadı: #{reservation_id}")
                return
                
            # Get branch and staff
            branch = Branch.query.get(reservation.branch_id)
            staff = Staff.query.get(reservation.staff_id)
            
            if not branch or not staff:
                logger.error(f"Branch or staff not found for reservation {reservation_id}")
                send_message(chat_id, f"❌ Rezervasyon #{reservation_id} için şube veya personel bilgisi bulunamadı")
                return
                
            # Record customer information for logging
            customer_name = reservation.customer_name
            customer_phone = reservation.customer_phone
            reservation_date_str = reservation.reservation_date.strftime('%d.%m.%Y')
            reservation_time_str = reservation.reservation_time.strftime('%H:%M')
            branch_id = reservation.branch_id
            
            # Calculate advance payment for reference
            advance_payment = 0
            try:
                advance_payment = (reservation.advance_payment_percentage / 100) * reservation.total_price
            except:
                advance_payment = 0
                
            # İptal tipini belirle
            cancel_type = "REFUND" if with_refund else "NORMAL"
            cancel_type_tr = "TAM İADE" if with_refund else "NORMAL"
            
            # Calculate advance payment for revenue tracking
            advance_amount = (reservation.advance_payment_percentage / 100) * reservation.total_price
            
            # Set is_canceled flag instead of deleting the reservation
            reservation.is_canceled = True
            reservation.cancel_type = cancel_type
            
            # If this is not a refund cancellation, keep advance payment in revenue
            if not with_refund and advance_amount > 0:
                reservation.cancel_revenue = advance_amount
            else:
                reservation.cancel_revenue = 0
                
            # Add log entry
            Log.add_log(
                log_type="RESERVATION",
                action="CANCEL",
                details=f"Rezervasyon Telegram ile iptal edildi ({cancel_type_tr}): {customer_name} ({reservation_date_str} {reservation_time_str}) - İptal Eden: {operator_name}" + 
                       (f" - İade: ₺{advance_payment:.2f}" if with_refund else ""),
                branch_id=branch_id
            )
            
            # Değişiklikleri kaydet
            db.session.commit()
            
            # Send notification of successful cancellation
            send_cancellation_notification(reservation, branch, staff, with_refund, operator_name)
            
            # Confirm to the user who issued the command
            action_type = "tam iade ile" if with_refund else ""
            send_message(chat_id, f"✅ #{reservation_id} numaralı rezervasyon {action_type} başarıyla iptal edildi!")
        
    except Exception as e:
        logger.error(f"Error processing cancellation: {e}")
        import traceback
        logger.error(f"Detailed error: {traceback.format_exc()}")
        send_message(chat_id, f"❌ Rezervasyon iptali sırasında hata oluştu: {str(e)}")

def start_telegram_bot():
    """
    Start the Telegram bot with command handlers in polling mode
    """
    global bot_updater, update_id_offset
    
    with bot_lock:
        # Önce mevcut bir bot çalışıyorsa durdur
        if bot_updater is not None:
            try:
                logger.info("Stopping existing bot updater before starting a new one")
                bot_updater.stop()
                bot_updater = None
            except Exception as e:
                logger.error(f"Error stopping existing bot updater: {e}")
            
        token = get_bot_token()
        if not token:
            logger.error("Cannot start Telegram bot, token not set")
            return
            
        try:
            logger.info("Starting Telegram bot in polling mode")
            
            # No need to create custom request object for this version
            
            # Set a reasonable default offset value - we don't need to check initial updates
            if update_id_offset == 0:
                update_id_offset = 1
            
            # Create updater with proper settings
            updater = Updater(token=token)
            
            # Initialize dispatcher and error handlers
            dispatcher = updater.dispatcher
            
            # Register command handlers
            register_command_handlers(dispatcher)
            
            # Set up an error handler
            def error_handler(update, context):
                try:
                    logger.error(f"Update {update} caused error: {context.error}")
                except Exception as e:
                    logger.error(f"Error in error handler: {e}")
            
            dispatcher.add_error_handler(error_handler)
            
            # Start the bot in a non-blocking way, dropping pending updates
            # to avoid processing old commands when the bot restarts
            logger.info(f"Starting polling with offset={update_id_offset}")
            updater.start_polling(
                drop_pending_updates=True, 
                timeout=20,
                allowed_updates=['message']
            )
            
            # Store updater for later reference
            bot_updater = updater
            
            logger.info("Telegram bot started successfully in polling mode")
        except Exception as e:
            logger.error(f"Error starting Telegram bot: {e}")
            import traceback
            logger.error(f"Detailed error: {traceback.format_exc()}")
        
def start_webhook(webhook_url, webhook_port=8443, cert_path=None, key_path=None):
    """
    Start the Telegram bot with command handlers in webhook mode
    
    Args:
        webhook_url (str): The URL for the webhook (e.g., https://example.com/webhook)
        webhook_port (int): The port to listen on (default: 8443)
        cert_path (str): Path to the SSL certificate file
        key_path (str): Path to the SSL private key file
    """
    global bot_updater
    
    # Only start if not already running
    if bot_updater is not None:
        logger.info("Bot updater already running, skipping start")
        return
        
    token = get_bot_token()
    if not token:
        logger.error("Cannot start Telegram bot, token not set")
        return
        
    try:
        logger.info(f"Starting Telegram bot in webhook mode: {webhook_url}")
        updater = Updater(token=token)
        dispatcher = updater.dispatcher
        
        # Register command handlers
        register_command_handlers(dispatcher)
        
        # Extract webhook path from URL
        import urllib.parse
        webhook_path = urllib.parse.urlparse(webhook_url).path
        
        # Configure and start webhook
        if cert_path and key_path:
            # Use self-signed certificate
            updater.start_webhook(
                listen='0.0.0.0',
                port=webhook_port,
                url_path=webhook_path,
                webhook_url=webhook_url,
                cert=cert_path,
                key=key_path
            )
            logger.info(f"Webhook set up with custom certificate: {cert_path}")
        else:
            # Use Let's Encrypt or other certificate managed by the server
            updater.start_webhook(
                listen='0.0.0.0',
                port=webhook_port,
                url_path=webhook_path,
                webhook_url=webhook_url
            )
            logger.info("Webhook set up without custom certificate")
        
        # Store updater for later reference
        bot_updater = updater
        
        logger.info("Telegram bot started successfully in webhook mode")
    except Exception as e:
        logger.error(f"Error starting Telegram bot in webhook mode: {e}")
        import traceback
        logger.error(f"Detailed error: {traceback.format_exc()}")
        
def handle_id_command(update, context):
    """
    Handle /id command - Show chat ID of the current chat (useful for setting up new branches)
    """
    try:
        logger.info(f"Received /id command in chat {update.effective_chat.id}")
        chat_id = update.effective_chat.id
        
        # Send chat ID information
        message = f"""
<b>📣 TELEGRAM KANAL BİLGİLERİ 📣</b>
━━━━━━━━━━━━━━━━━━━━━━━

🆔 <b>Chat ID:</b> <code>{chat_id}</code>

💡 <i>Bu ID'yi şube ayarlarındaki Telegram Chat ID alanına girerek bu gruba bildirim gönderilmesini sağlayabilirsiniz.</i>

👉 Ayarlar → Şubeler → Şube Düzenle → Telegram Chat ID
━━━━━━━━━━━━━━━━━━━━━━━
"""
        update.message.reply_html(message)
            
    except Exception as e:
        logger.error(f"Error in id command: {e}")
        import traceback
        logger.error(f"Detailed error: {traceback.format_exc()}")
        update.message.reply_text(f"Hata oluştu: {str(e)}")

def register_command_handlers(dispatcher):
    """
    Register all command handlers with a dispatcher
    """
    dispatcher.add_handler(CommandHandler("iptal", handle_iptal_command))
    dispatcher.add_handler(CommandHandler("iade", handle_iade_command))
    dispatcher.add_handler(CommandHandler("rez", handle_rez_command))
    dispatcher.add_handler(CommandHandler("detay", handle_detay_command))
    dispatcher.add_handler(CommandHandler("id", handle_id_command))

def stop_telegram_bot():
    """
    Stop the Telegram bot if it's running
    """
    global bot_updater
    
    with bot_lock:
        if bot_updater is not None:
            logger.info("Stopping Telegram bot")
            try:
                # Use idle=False to avoid hanging
                bot_updater.stop()
                bot_updater = None
                logger.info("Telegram bot stopped")
            except Exception as e:
                logger.error(f"Error stopping Telegram bot: {e}")
                import traceback
                logger.error(f"Detailed error: {traceback.format_exc()}")
                # Ensure updater is set to None even if stop fails
                bot_updater = None